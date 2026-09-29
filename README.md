# Fullstack AI WhatsApp Integration

WhatsApp inbound messages arrive at a public webhook, are authenticated with Supabase OAuth, then dispatch to an internal handler that replies through the WhatsApp Cloud API. Two seams define the system. Everything else is private.

## Tree

```
.
├── backend/
│   ├── src/
│   │   ├── api/whatsapp/
│   │   │   ├── dedup.test.ts
│   │   │   ├── delegation-seam.test.ts
│   │   │   ├── delegation.test.ts
│   │   │   ├── delegation.ts
│   │   │   ├── deps.ts
│   │   │   ├── grants.test.ts
│   │   │   ├── handler.test.ts
│   │   │   ├── handler.ts
│   │   │   ├── handshake.test.ts
│   │   │   ├── payload.test.ts
│   │   │   ├── rate-limit.test.ts
│   │   │   ├── schema.ts
│   │   │   ├── signature.test.ts
│   │   │   ├── signature.ts
│   │   │   ├── telemetry.test.ts
│   │   │   ├── test-helpers.ts
│   │   │   ├── webhook.test.ts
│   │   │   └── webhook.ts
│   │   ├── app.ts
│   │   ├── config.test.ts
│   │   ├── config.ts
│   │   ├── index.ts
│   │   ├── telemetry.test.ts
│   │   └── telemetry.ts
│   ├── Dockerfile
│   ├── bun.lock
│   └── package.json
├── frontend/
│   └── package.json
├── supabase/
│   └── migrations/
│       └── 0001_whatsapp_rls.sql
├── .env.example
├── biome.json
├── docker-compose.yml
├── otel-collector-config.yaml
├── package.json
└── tsconfig.json
```

## Architecture

```
WhatsApp ──POST /api/whatsapp/webhook──> Entry Seam ──> Exit Seam ──> WhatsApp Cloud API
                                           │                │
                                     grant + delegation   Cloud API + escalation
```

## Route Table

| Method | Path | File | Status |
| --- | --- | --- | --- |
| GET | `/api/whatsapp/webhook` | `backend/src/api/whatsapp/webhook.ts` | tested |
| POST | `/api/whatsapp/webhook` | `backend/src/api/whatsapp/webhook.ts` | tested |
| POST | `/api/whatsapp/handler` | `backend/src/api/whatsapp/handler.ts` | tested |

`Status` values: `planned`, `implemented`, `tested`.

## Entry Seam

`backend/src/api/whatsapp/webhook.ts`

- Mounted at `/api/whatsapp` by `backend/src/app.ts`.
- GET is Meta's subscription handshake: echoes `hub.challenge` as plain text
  with `200` when `hub.mode` is `subscribe` and `hub.verify_token` matches.
  Otherwise `403 forbidden`.
- POST requires a valid `X-Hub-Signature-256` header, computed as an HMAC-SHA256
  of the raw body and compared in constant time. Missing or mismatched:
  `401 {"status":"unauthorized"}`.
- The body is validated against a zod envelope (`schema.ts`). Invalid:
  `400 {"status":"invalid_payload","issues":[...]}`, where `issues` are field
  paths only, never values.
- Replay of a message id already seen for the same `entry` and `field`:
  `200 {"status":"duplicate"}`. Meta retries for up to 36 hours, so a duplicate
  is a success, not an error.
- Rate limit is per WABA (`entry[0].id`), not per IP, since a single Meta edge
  carries every sender's traffic. Over capacity:
  `429 {"status":"rate_limited"}`.
- An admitted message returns `200 {"status":"ok","grant_id":"..."}`, where the
  grant is the only credential the Exit Seam accepts.

Test: `backend/src/api/whatsapp/webhook.test.ts`, plus the per-concern files
listed in the tree.

## Exit Seam

`backend/src/api/whatsapp/handler.ts`

- Publicly routed, so the gate is a single-use grant: 122 bits of randomness,
  consumed on first read, 60s TTL, capped at 200 entries. Replay or expiry:
  `401 {"status":"unauthorized"}`.
- The body carries `grant_id` and nothing else. Subject, scope, and token all
  come from the grant record; a body-supplied `sub` is rejected by the schema.
- A valid grant is not authority on its own. Its delegation token must still
  verify (RFC 8693, ES256, 60s expiry), name this service as audience, and
  carry `whatsapp:write` for an authorized actor. Otherwise
  `403 {"status":"forbidden"}`.
- Accepted: `200 {"status":"accepted"}`.
- WhatsApp Cloud API dispatch and escalation actions: planned.

Test: `backend/src/api/whatsapp/handler.test.ts`, `grants.test.ts`,
`delegation-seam.test.ts`.

## Auth

- Provider: Supabase OAuth.
- Requested scopes: `whatsapp:read whatsapp:write`.
- Granted scope is the intersection of the request with the allowlist, and the
  Exit Seam independently requires `whatsapp:write`. Two gates: narrowing at
  issuance is a default, not the check.
- Delegation tokens follow RFC 8693: `sub` is the `wa_id`, `act.sub` is the
  acting agent, `may_act` names who may act on the subject, `scope` is
  space-delimited, and `jti` makes each token distinct. Signing keys are
  generated per process, so a token minted by one instance never verifies at
  another.
- Supabase JWT verification at the seams: planned. The current gate is the
  single-use grant, which is local state and does not survive a restart.

## Observability

- `otel-collector-config.yaml` receives OTLP on `4317` (gRPC) and `4318` (HTTP)
  and exports traces to OpenObserve via `otlp_http`, alongside `debug`.
- `backend/src/telemetry.ts` wires the SDK: `BatchSpanProcessor` to an
  `OTLPTraceExporter`, flushed on `SIGINT` and `SIGTERM` so the batch before a
  deploy is not lost.
- Three spans: `whatsapp.webhook.verify`, `whatsapp.webhook.post`,
  `whatsapp.handler.post`.
- Span attributes are a closed set. `SPAN_ATTRIBUTE_ALLOWLIST` in
  `webhook.ts` is enforced by `OtelTelemetry`, so an attribute outside it is
  dropped rather than exported, and the collector redacts as a second,
  independent check.
- The raw body, sender phone number, app secret, grant id, and delegation
  token never reach a trace. Tests assert each of those absences.
- Cloud API dispatch spans: planned.

## Data

`supabase/migrations/0001_whatsapp_rls.sql`

- `webhook_events` and `delegation_grants`: RLS enabled, all privileges revoked
  from `anon` and `authenticated`, and no policies. `service_role` has
  `BYPASSRLS` and never evaluates policies, so writing one for it would be
  dead SQL.
- `whatsapp_conversations` and `whatsapp_messages`: real `auth.uid()`
  policies, scoped by `wa_id`. No update or delete policy: a user may open a
  thread but not rewrite or remove it.
- The compose `db` is a bare `postgres:16-alpine` with no `auth` schema, so
  these apply to a hosted Supabase project and are not exercised locally.

## Test Coverage

- `bun test` runs every test in `backend/src`.
- 136 tests across 13 files.

## Setup

```bash
git clone <repo-url>
cd factored-hackathon-2026-sol
bun install
cp .env.example .env
```

Edit `.env` with your Supabase and WhatsApp credentials.

Consumed variables:

| Variable | Required | Purpose |
| --- | --- | --- |
| `PORT` | no | Defaults to `4000`. |
| `WHATSAPP_APP_SECRET` | yes | Signs `X-Hub-Signature-256`. |
| `WHATSAPP_VERIFY_TOKEN` | yes | Answers the GET handshake. |
| `WHATSAPP_PHONE_ID` | no | Cloud API send target. Planned. |
| `WHATSAPP_TOKEN` | no | Cloud API credential. Planned. |
| `SUPABASE_URL` | no | Planned. |
| `SUPABASE_SERVICE_ROLE_KEY` | no | Planned. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | Defaults to `http://localhost:4318`. |

`backend/src/config.ts` validates the environment before the server binds and
reports every missing variable at once, naming variables without echoing their
values. A blank app secret would otherwise reject every webhook with a `401`,
which reads as a Meta outage rather than a missing variable.

## Docker

```bash
docker compose up --build
```

Services: `backend` (`4000`), `otel-collector` (`4317`, `4318`, `8888`),
`openobserve` (`5080`), `db` (`5432`). The `frontend` service is commented out
in `docker-compose.yml` until `frontend/Dockerfile` exists.

## Run

```bash
bun run dev     # backend, watch mode
bun run start   # backend, production
bun test        # seam tests
bun run check   # biome lint
```

Backend listens on `config.port`, validated at boot and read in
`backend/src/index.ts`.

## Contributing

```bash
git switch -c feat/entry-seam-webhook
bun test
bun run check
```

- `README.md` is the source of truth. Code dictates the README.
- Exact paths only. One route, one file.
- Unimplemented work is documented as `planned`.
- A new endpoint requires a failing seam test first.
- `frontend/package.json` exists; the Next.js app is planned.
- Backend routes live in `backend/src/api/whatsapp/`.

## License

MIT © 2026 Your Organization

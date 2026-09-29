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
│   │   ├── health.test.ts
│   │   ├── index.ts
│   │   ├── telemetry.test.ts
│   │   └── telemetry.ts
│   ├── Dockerfile
│   ├── bun.lock
│   └── package.json
├── docs/
│   └── merge-recipe.md
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
| GET | `/health` | `backend/src/app.ts` | tested |
| GET | `/api/whatsapp/webhook` | `backend/src/api/whatsapp/webhook.ts` | tested |
| POST | `/api/whatsapp/webhook` | `backend/src/api/whatsapp/webhook.ts` | tested |
| POST | `/api/whatsapp/handler` | `backend/src/api/whatsapp/handler.ts` | tested |

`Status` values: `planned`, `implemented`, `tested`.

## Health

`GET /health` — mounted at the root, outside `/api/whatsapp`, and is not a
WhatsApp seam.

| Case | Status | Body |
| --- | --- | --- |
| Boot validation passed | `200` | `{"status":"ok"}` |
| Boot validation failed | `503` | `{"status":"unavailable","errors":["VAR", ...]}` |

- The healthy body is a fixed literal. A health endpoint is reachable by
  anything that can reach the container, so there is nothing dynamic to
  disclose: no version, no uptime, no host detail.
- The unhealthy branch names the failing variables and never their values.
- An invalid config with an empty error list still reads as unhealthy, so a
  broken validator cannot silently report the service as up.
- Non-`GET` methods get `405`, so a bug that POSTs here is visible rather than
  looking like a typo.

`backend/src/index.ts` binds the port even when validation fails, so the
process can report *which* variable was wrong instead of exiting and leaving
an orchestrator guessing.

Test: `backend/src/health.test.ts`.

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
- 145 tests across 14 files.

## Setup

```bash
git clone <repo-url>
cd factored-hackathon-2026-sol
bun install
cp .env.example .env
```

Edit `.env` with your Supabase and WhatsApp credentials. `.env.example`
documents every variable; `docker compose config --variables` lists what
compose actually reads and whether it is required.

| Variable | Required by compose | Used by |
| --- | --- | --- |
| `PORT` | no (default `4000`) | backend. Must be an integer in 1-65535. |
| `WHATSAPP_APP_SECRET` | **yes** | Signs `X-Hub-Signature-256`. |
| `WHATSAPP_VERIFY_TOKEN` | **yes** | Answers the GET handshake. |
| `WHATSAPP_PHONE_ID` | no | Cloud API send target. Planned. |
| `WHATSAPP_TOKEN` | no | Cloud API credential. Planned. |
| `SUPABASE_URL` | no | Planned. |
| `SUPABASE_SERVICE_ROLE_KEY` | no | Planned. |
| `SUPABASE_ANON_KEY` | no | commented-out `frontend` |
| `POSTGRES_DB` | no (default `postgres`) | `db` |
| `POSTGRES_USER` | no (default `postgres`) | `db` |
| `POSTGRES_PASSWORD` | **yes** | `db` |
| `POSTGRES_HOST_AUTH_METHOD` | no (default `scram-sha-256`) | `db` |
| `ZO_ROOT_USER_EMAIL` | **yes** | `openobserve` |
| `ZO_ROOT_USER_PASSWORD` | **yes** | `openobserve` |
| `OPENOBSERVE_AUTH_HEADER` | **yes** | `otel-collector` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | backend, defaults to `http://localhost:4318`. |

A required variable that is missing *or blank* stops `docker compose up` with a
named error. That is the point: the previous revision shipped inline defaults
that were the same credentials, so a forgotten `.env` produced a running stack
reaching the network with a published password.

`backend/src/config.ts` validates the environment before the server binds and
reports every missing variable at once, naming variables without echoing their
values. A blank app secret would otherwise reject every webhook with a `401`,
which reads as a Meta outage rather than a missing variable.

## Docker

```bash
docker compose up --build
```

Services: `backend` (`4000`), `otel-collector` (`4317`, `4318`),
`openobserve` (`5080`), `db` (`5432`). The `frontend` service is commented out
in `docker-compose.yml` until `frontend/Dockerfile` exists.

### Network bindings

Every published port binds `127.0.0.1`. Nothing in this stack needs LAN
reachability, and every service holds either data or credentials. Verified with
`lsof`: all five listen on loopback, and a request to the host's LAN address is
refused.

The collector's `8888` is no longer published. `otelcol-contrib` has served no
internal metrics there by default since the telemetry defaults changed, and this
config has no `service.telemetry` block, so the port forwarded to nothing.
Measured: the container starts only `4317` and `4318`.

### Readiness

`depends_on` carries a `condition` on every edge, so a service is not started
against a dependency that cannot serve it yet.

| Service | Gate | Why that form |
| --- | --- | --- |
| `backend` | `db`, `otel-collector` healthy | both expose a healthcheck |
| `otel-collector` | `openobserve-probe` completed | see below |
| `openobserve-probe` | `openobserve` started | one-shot job |

The `openobserve/openobserve` image is distroless: `/bin`, `/sbin` and
`/usr/bin` are empty directories and the only executable is `/openobserve`,
which starts a second server rather than probing one. An in-container HTTP
probe cannot run. Docker records such a check as `ExitCode -1` and marks the
container unhealthy forever, blocking every dependent — worse than no probe.
So `openobserve-probe` runs the check in a `curlimages/curl` container against
`/healthz` (the unauthenticated path; `/api` returns `401` and would read as
unhealthy while being fine). It is one-shot, so the condition is
`service_completed_successfully`: a container that has exited never reaches
`healthy`, and waiting for that hangs forever.

The collector healthcheck execs `/otelcol-contrib validate` directly. No shell
is needed, and it is a real check: it fails when the pipeline config is invalid,
which a port probe cannot see. The backend's uses `bun -e` for the same reason
`curl` is not in `oven/bun`.

### Privilege

`cap_drop: ALL` on `backend`, `otel-collector` and `openobserve`;
`no-new-privileges` everywhere; `read_only` plus a `/tmp` tmpfs on the two that
do not need to write (`backend`, `otel-collector`); memory and CPU ceilings on
all four.

`db` is the exception, and it is a measured one:

- `cap_add: [CHOWN, FOWNER, SETGID, SETUID, DAC_OVERRIDE]` alongside
  `cap_drop: ALL`. The entrypoint starts as root to chown `PGDATA` and then
  drops to the `postgres` user; with nothing granted it dies on `operation not
  permitted` at `chmod`. These five are the verified minimum.
- No `read_only`. `PGDATA` is a volume, but initdb and the entrypoint also write
  to `/var/run/postgresql` and `/tmp`.

`local` socket auth stays `trust`, which is the image default. It is only
reachable from inside the container; host auth is `scram-sha-256` and a wrong
password over TCP is refused.

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

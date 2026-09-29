# Fullstack AI WhatsApp Integration

WhatsApp inbound messages arrive at a public webhook, are authenticated with Supabase OAuth, then dispatch to an internal handler that replies through the WhatsApp Cloud API. Two seams define the system. Everything else is private.

## Tree

```
.
├── backend/
│   ├── src/
│   │   ├── api/whatsapp/
│   │   │   ├── handler.test.ts
│   │   │   ├── handler.ts
│   │   │   ├── webhook.test.ts
│   │   │   └── webhook.ts
│   │   ├── app.ts
│   │   ├── config.test.ts
│   │   ├── config.ts
│   │   ├── health.test.ts
│   │   └── index.ts
│   ├── Dockerfile
│   ├── bun.lock
│   └── package.json
├── docs/
│   └── merge-recipe.md
├── frontend/
│   └── package.json
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
                                    Supabase JWT      Cloud API + escalation
```

## Route Table

| Method | Path | File | Status |
| --- | --- | --- | --- |
| GET | `/health` | `backend/src/app.ts` | tested |
| POST | `/api/whatsapp/webhook` | `backend/src/api/whatsapp/webhook.ts` | implemented |
| POST | `/api/whatsapp/handler` | `backend/src/api/whatsapp/handler.ts` | implemented |

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
- Returns `200` with `{"status":"ok"}`.
- WhatsApp signature verification: planned.
- Test: `backend/src/api/whatsapp/webhook.test.ts`.

## Exit Seam

`backend/src/api/whatsapp/handler.ts`

- Returns `200` with `{"status":"accepted"}`.
- WhatsApp Cloud API dispatch and escalation actions: planned.
- Test: `backend/src/api/whatsapp/handler.test.ts`.

## Auth

- Provider: Supabase OAuth.
- Scopes: `whatsapp:read/write`.
- JWT verification at the seams: planned.

## Observability

- `otel-collector-config.yaml` receives OTLP on `4317` (gRPC) and `4318` (HTTP), exports traces via the `debug` exporter.
- OpenObserve sink and backend instrumentation: planned.

## Test Coverage

- `bun test` runs the seam tests.
- Target coverage for seam tests: planned.

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
| `PORT` | no (default `4000`) | backend |
| `WHATSAPP_APP_SECRET` | **yes** | backend, boot validation |
| `WHATSAPP_VERIFY_TOKEN` | **yes** | backend, boot validation |
| `WHATSAPP_PHONE_ID` | no | planned |
| `WHATSAPP_TOKEN` | no | planned |
| `SUPABASE_URL` | no | planned |
| `SUPABASE_SERVICE_ROLE_KEY` | no | planned |
| `SUPABASE_ANON_KEY` | no | commented-out `frontend` |
| `POSTGRES_DB` | no (default `postgres`) | `db` |
| `POSTGRES_USER` | no (default `postgres`) | `db` |
| `POSTGRES_PASSWORD` | **yes** | `db` |
| `POSTGRES_HOST_AUTH_METHOD` | no (default `scram-sha-256`) | `db` |
| `ZO_ROOT_USER_EMAIL` | **yes** | `openobserve` |
| `ZO_ROOT_USER_PASSWORD` | **yes** | `openobserve` |
| `OPENOBSERVE_AUTH_HEADER` | **yes** | `otel-collector` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | backend on the host |

A required variable that is missing *or blank* stops `docker compose up` with a
named error. That is the point: the previous revision shipped inline defaults
that were the same credentials, so a forgotten `.env` produced a running stack
reaching the network with a published password.

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

Backend listens on `process.env.PORT ?? 4000`, set in `backend/src/index.ts`.

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

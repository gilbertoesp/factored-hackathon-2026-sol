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
│   │   └── index.ts
│   ├── Dockerfile
│   ├── bun.lock
│   └── package.json
├── frontend/
│   └── package.json
├── .env.example
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
| POST | `/api/whatsapp/webhook` | `backend/src/api/whatsapp/webhook.ts` | implemented |
| POST | `/api/whatsapp/handler` | `backend/src/api/whatsapp/handler.ts` | implemented |

`Status` values: `planned`, `implemented`, `tested`.

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

Edit `.env` with your Supabase and WhatsApp credentials. Consumed variables: `PORT`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `WHATSAPP_PHONE_ID`, `WHATSAPP_TOKEN`, `OTEL_EXPORTER_OTLP_ENDPOINT`.

## Docker

```bash
docker compose up --build
```

Services: `backend` (`4000`), `otel-collector` (`4317`, `4318`, `8888`), `openobserve` (`5080`), `db` (`5432`). The `frontend` service is commented out in `docker-compose.yml` until `frontend/Dockerfile` exists.

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

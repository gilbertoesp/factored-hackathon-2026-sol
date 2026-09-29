# Merge recipe: `chore/compose-zero-trust` <- `feat/webhook`

Rehearsed and verified 2026-09-29, then aborted to keep the branch reviewable.
Result of the rehearsal: 145 tests / 14 files pass, `tsc --noEmit` clean, Biome
clean, `docker compose up --build` healthy on all four services.

Of the 28 changed files, the 17 carrying actual feature work — delegation,
signature, schema, grants, telemetry, the RLS migration, every test — auto-merge
untouched. Six conflict, and all six are bootstrap or deployment config.

## Resolution

| File | Resolution |
| --- | --- |
| `docker-compose.yml` | take ours |
| `.env.example` | take ours |
| `backend/package.json` | take ours, add two deps |
| `backend/src/app.ts` | edit, see below |
| `backend/src/index.ts` | edit, see below |
| `README.md` | union — **not** either side |

### Take ours: `docker-compose.yml`, `.env.example`

`feat/webhook` changed these in the same direction, less far. It added the two
WhatsApp secrets as bare `${VAR}` and wrapped `OPENOBSERVE_AUTH_HEADER` in
`${VAR:-<literal>}` so the published credential still resolved when unset. This
branch uses `${VAR:?}` throughout, which refuses a missing *or blank* value.

Verified as a strict superset before taking ours — every variable
`feat/webhook` reads is still read here:

    diff <(git show :3:docker-compose.yml | grep -oE '\$\{[A-Z_]+' | sed 's/\${//' | sort -u) \
         <(grep -oE '\$\{[A-Z_]+' docker-compose.yml   | sed 's/\${//' | sort -u)

Only additions should appear on the right: `POSTGRES_*`, `SUPABASE_ANON_KEY`,
`ZO_ROOT_*`.

### `backend/package.json`

Add only:

    "@opentelemetry/resources": "^1.30.1",
    "@opentelemetry/sdk-trace-base": "^1.30.1",

The devDependencies reorder in the conflict is cosmetic. Both sides already pin
Biome `2.5.14`. `backend/bun.lock` is *not* in the conflict list — it auto-merges
carrying both — so `bun install` in `backend/` should report "no changes".

### `backend/src/app.ts` — the one real design decision

Both sides changed `createApp`'s signature. An intersection type reconciles them
so that **no call site on either branch needs editing**:

    export function createApp(
        options: Partial<WebhookDeps> & AppOptions = {},
    ): Hono {
        const app = new Hono();
        const { config, ...overrides } = options;
        const deps: WebhookDeps = { ...defaultWebhookDeps(), ...overrides };
        const state: HealthState = config ?? { valid: true, errors: [] };

        app.route("/", healthRouter(state));
        app.route("/api/whatsapp", createHandlerRouter(deps));
        app.route("/api/whatsapp", createWebhookRouter(deps));
        return app;
    }

`feat/webhook`'s tests call `createApp({ secrets, telemetry })`; this branch's
health tests call `createApp({ config })`. Both compile against the
intersection, so zero test files are touched.

Keep `feat/webhook`'s `defaultWebhookDeps()`. Its comment earns its keep:
resolving deps per-router gives each router a private grant store, so a grant
minted at the Entry Seam fails at the Exit Seam on a live server.

### `backend/src/index.ts`

`feat/webhook` has loadConfig + telemetry + signal flush; this branch has
loadConfig + bind-anyway-for-503. Union them:

    interface Booted {
        port: number;
        build: () => Hono;
        shutdown: () => Promise<void>;
    }

    function boot(): Booted {
        try {
            const config = loadConfig(process.env);
            const traces = createOtelTelemetry({ /* ... */ });
            return {
                port: config.port,
                build: () => createApp({ secrets: {...}, telemetry: traces.telemetry }),
                shutdown: () => traces.shutdown(),
            };
        } catch (error) {
            if (!(error instanceof ConfigError)) throw error;
            console.error(`backend misconfigured: ${error.message}`);
            return {
                port: Number(process.env.PORT ?? 4000),
                build: () => createApp({ config: { valid: false, errors: error.missing } }),
                shutdown: async () => {},
            };
        }
    }

    const { port, build, shutdown } = boot();
    export const app = build();
    export const server = Bun.serve({ port, fetch: app.fetch });

On the failure path no secrets are passed down, so no route can serve with a
blank one.

### `README.md`

`feat/webhook`'s is the real contract — handshake, signature, dedup, grants,
delegation, spans, RLS. This branch adds the Health section, the hardened
Docker sections, and a 16-row env table. `--ours` discards the entire seam
contract, which defeats the point of the SSoT. Graft the two, and set the test
count to whatever the merged suite actually reports.

## Verify

    bun test
    bun x tsc --noEmit
    bunx @biomejs/biome check .    # then: git checkout package.json
    cd backend && bun install      # should say "no changes"

Then the checks that catch what tests cannot:

    WHATSAPP_APP_SECRET=sec WHATSAPP_VERIFY_TOKEN=vtok PORT=4192 \
      bun run backend/src/index.ts
    curl -s localhost:4192/health                                # {"status":"ok"}
    curl -s "localhost:4192/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=vtok&hub.challenge=xyz"
    curl -si -XPOST localhost:4192/api/whatsapp/webhook -d '{}'   # 401, unsigned

    env -u WHATSAPP_APP_SECRET -u WHATSAPP_VERIFY_TOKEN PORT=4193 \
      bun run backend/src/index.ts
    curl -s localhost:4193/health    # 503, naming the missing variables

# Merge recipe: `feat/webhook` <- `chore/compose-zero-trust`

Already done — merged as `28fe05d`. Kept because the resolution is subtle in a
way that produces a silently regressed stack if you get it backwards.

## Read this before using the table

**"ours" and "theirs" are not fixed. Name the branch.** The table below was
written standing on `chore/compose-zero-trust`. The merge was then performed
standing on `feat/webhook`, which is the common case, and there the labels
invert.

| File | Take the `chore/compose-zero-trust` version | Never take |
| --- | --- | --- |
| `docker-compose.yml` | theirs | `feat/webhook`'s |
| `.env.example` | theirs | `feat/webhook`'s |
| `backend/package.json` | theirs, add two deps | — |
| `backend/src/app.ts` | edit, see below | either side verbatim |
| `backend/src/index.ts` | edit, see below | either side verbatim |
| `README.md` | union — **not** either side | either side verbatim |

Taking `feat/webhook`'s `docker-compose.yml` is the failure mode. It publishes
all six ports on every interface and wraps `OPENOBSERVE_AUTH_HEADER` in
`${VAR:-<literal>}`, so the hardcoded base64 credential resolves when the
variable is unset. Verify before you commit, since nothing warns you:

    grep -c '\${[A-Z_]*:?' docker-compose.yml    # must be 7
    grep -E '^\s+- "127'  docker-compose.yml     # must be 5, all loopback

Five published ports: 4000, 4317, 4318, 5080, 5432. A sixth match is the
commented-out `frontend` line. Four guards and any interface-wide port means you
took the wrong side.

## Per-file notes

Both branches changed these in the same direction, less far. `feat/webhook`
added the two WhatsApp secrets as bare `${VAR}`; `chore/compose-zero-trust`
uses `${VAR:?}` throughout, which refuses a missing *or blank* value.

Verified as a strict superset before taking that side — every variable
`feat/webhook` reads is still read there:

    diff <(git show :3:docker-compose.yml | grep -oE '\$\{[A-Z_]+' | sed 's/\${//' | sort -u) \
         <(grep -oE '\$\{[A-Z_]+' docker-compose.yml   | sed 's/\${//' | sort -u)

Only additions should appear on the right: `POSTGRES_*`, `SUPABASE_ANON_KEY`,
`ZO_ROOT_*`.

### `backend/package.json`

Take `chore/compose-zero-trust`'s, then add:

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

`feat/webhook`'s tests call `createApp({ secrets, telemetry })`;
`chore/compose-zero-trust`'s health tests call `createApp({ config })`. Both
compile against the intersection, so zero test files are touched.

Keep `feat/webhook`'s `defaultWebhookDeps()`. Its comment earns its keep:
resolving deps per-router gives each router a private grant store, so a grant
minted at the Entry Seam fails at the Exit Seam on a live server.

### `backend/src/index.ts`

`feat/webhook` has loadConfig + telemetry + signal flush;
`chore/compose-zero-trust` has loadConfig + bind-anyway-for-503. Union them:

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
delegation, spans, RLS. `chore/compose-zero-trust` adds the Health section, the
hardened Docker sections, and a 16-row env table. Taking either side verbatim
discards half the contract, which defeats the point of the SSoT. Graft the two.
Concretely: the Tree listing is a union, the Route Table keeps `feat/webhook`'s
`tested` statuses and gains the `GET /health` row, and the env table takes the
16 rows with `feat/webhook`'s purpose descriptions. Set the test count to
whatever the merged suite actually reports — 145 across 14.

## Verify

    bun test
    bun x tsc --noEmit
    bunx @biomejs/biome check .    # then: git restore --staged package.json
    cd backend && bun install      # should say "no changes"

`git add -u` will stage a dirty `package.json` along with the merge. Restore it
afterwards unless that change is meant to ship.

Then the checks that catch what tests cannot:

    WHATSAPP_APP_SECRET=sec WHATSAPP_VERIFY_TOKEN=vtok PORT=4192 \
      bun run backend/src/index.ts
    curl -s localhost:4192/health                                # {"status":"ok"}
    curl -s "localhost:4192/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=vtok&hub.challenge=xyz"
    curl -si -XPOST localhost:4192/api/whatsapp/webhook -d '{}'   # 401, unsigned
    curl -si -XPOST   localhost:4192/health                       # 405

    env -u WHATSAPP_APP_SECRET -u WHATSAPP_VERIFY_TOKEN PORT=4193 \
      bun run backend/src/index.ts
    curl -s localhost:4193/health    # 503, naming the missing variables

And the stack, which is the only check that exercises the compose guards:

    docker compose up --build -d
    docker compose ps            # all four services healthy
    lsof -nP -iTCP:4000 -sTCP:LISTEN   # 127.0.0.1:4000, not *:4000

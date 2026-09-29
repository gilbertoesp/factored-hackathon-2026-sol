import { Hono } from "hono";
import { defaultWebhookDeps } from "./api/whatsapp/deps";
import { createHandlerRouter } from "./api/whatsapp/handler";
import { createWebhookRouter, type WebhookDeps } from "./api/whatsapp/webhook";

/**
 * The outcome of boot-time environment validation. Passed in rather than
 * read from `process.env` so a test can exercise the unhealthy branch without
 * mutating the environment of the whole process.
 */
export interface HealthState {
	valid: boolean;
	/** Names of the offending variables. Values are never included. */
	errors: string[];
}

export interface AppOptions {
	config?: HealthState;
}

/**
 * Liveness and readiness in one probe.
 *
 * `GET /health` is what the container healthcheck calls, so it answers the
 * question an orchestrator actually needs: will this process serve traffic? A
 * process that bound its port but failed boot validation is listening and
 * broken at the same time, and a TCP probe cannot tell those apart.
 *
 * The response body is a fixed literal when healthy. Anything dynamic would be
 * one more thing to disclose, and a health endpoint is reachable by anything
 * that can reach the container.
 */
function healthRouter(state: HealthState): Hono {
	const router = new Hono();

	router.get("/health", (c) => {
		// An invalid config with an empty error list is treated as unhealthy.
		// Reading it as healthy would mean a broken validator silently reports
		// the service as up.
		if (!state.valid || state.errors.length > 0) {
			return c.json({ status: "unavailable", errors: state.errors }, 503);
		}
		return c.json({ status: "ok" }, 200);
	});

	// Hono answers an unmatched method with 404, which is indistinguishable
	// from a wrong path. 405 says the route exists and only GET is allowed, so
	// a bug that POSTs here is visible rather than looking like a typo.
	router.on(["POST", "PUT", "PATCH", "DELETE"], "/health", (c) =>
		c.json({ status: "method_not_allowed" }, 405),
	);

	return router;
}

/**
 * Builds the app with injected seams. Tests pass fresh deps per case so no
 * mutable state (dedup set, rate-limit bucket, grant store) is shared between
 * them.
 *
 * The deps are resolved once here and handed to both routers. Resolving
 * per-router would give each a private grant store, so a grant issued at the
 * Entry Seam could never be consumed at the Exit Seam.
 *
 * `AppOptions` is intersected rather than a second parameter so both existing
 * call shapes keep compiling: the webhook tests pass `{ secrets, telemetry }`,
 * the health tests pass `{ config }`.
 */
export function createApp(
	options: Partial<WebhookDeps> & AppOptions = {},
): Hono {
	const app = new Hono();
	const { config, ...overrides } = options;
	const deps: WebhookDeps = { ...defaultWebhookDeps(), ...overrides };
	const state: HealthState = config ?? { valid: true, errors: [] };

	// Mounted at the root, not under /api/whatsapp: it is not a WhatsApp seam
	// and must not inherit that route's contract.
	app.route("/", healthRouter(state));
	app.route("/api/whatsapp", createHandlerRouter(deps));
	app.route("/api/whatsapp", createWebhookRouter(deps));
	return app;
}

export const app = createApp();

export default app;

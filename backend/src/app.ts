import { Hono } from "hono";
import { handlerRouter } from "./api/whatsapp/handler";
import { webhookRouter } from "./api/whatsapp/webhook";

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

export function createApp(options: AppOptions = {}): Hono {
	const app = new Hono();
	const state: HealthState = options.config ?? { valid: true, errors: [] };

	// Mounted at the root, not under /api/whatsapp: it is not a WhatsApp seam
	// and must not inherit that route's contract.
	app.route("/", healthRouter(state));
	app.route("/api/whatsapp", handlerRouter);
	app.route("/api/whatsapp", webhookRouter);
	return app;
}

export const app = createApp();

export default app;

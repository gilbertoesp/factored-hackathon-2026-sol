import { Hono } from "hono";
import { createHandlerRouter } from "./api/whatsapp/handler";
import { createWebhookRouter, type WebhookDeps } from "./api/whatsapp/webhook";

/**
 * Builds the app with injected seams. Tests pass fresh deps per case so no
 * mutable state (dedup set, rate-limit bucket, grant store) is shared between
 * them. Production callers pass nothing and get module-default deps.
 */
export function createApp(overrides?: Partial<WebhookDeps>): Hono {
	const app = new Hono();
	app.route("/api/whatsapp", createHandlerRouter(overrides));
	app.route("/api/whatsapp", createWebhookRouter(overrides));
	return app;
}

export const app = createApp();

export default app;

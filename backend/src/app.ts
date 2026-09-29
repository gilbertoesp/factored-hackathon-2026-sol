import { Hono } from "hono";
import { defaultWebhookDeps } from "./api/whatsapp/deps";
import { createHandlerRouter } from "./api/whatsapp/handler";
import { createWebhookRouter, type WebhookDeps } from "./api/whatsapp/webhook";

/**
 * Builds the app with injected seams. Tests pass fresh deps per case so no
 * mutable state (dedup set, rate-limit bucket, grant store) is shared between
 * them.
 *
 * The deps are resolved once here and handed to both routers. Resolving
 * per-router would give each a private grant store, so a grant issued at the
 * Entry Seam could never be consumed at the Exit Seam.
 */
export function createApp(overrides?: Partial<WebhookDeps>): Hono {
	const app = new Hono();
	const deps: WebhookDeps = { ...defaultWebhookDeps(), ...overrides };
	app.route("/api/whatsapp", createHandlerRouter(deps));
	app.route("/api/whatsapp", createWebhookRouter(deps));
	return app;
}

export const app = createApp();

export default app;

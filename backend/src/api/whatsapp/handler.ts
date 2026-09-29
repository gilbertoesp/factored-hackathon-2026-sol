import { Hono } from "hono";
import { defaultWebhookDeps } from "./deps";
import type { WebhookDeps } from "./webhook";

export function createHandlerRouter(deps?: Partial<WebhookDeps>): Hono {
	const router = new Hono();
	const resolved = { ...defaultWebhookDeps(), ...deps };

	// Delegation token verification and Cloud API dispatch: added slice by slice.
	void resolved;

	router.post("/handler", (c) => c.json({ status: "accepted" }, 200));

	return router;
}

export const handlerRouter = createHandlerRouter();

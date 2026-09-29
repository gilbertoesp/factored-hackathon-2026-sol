import { Hono } from "hono";
import { handlerRouter } from "./api/whatsapp/handler";
import { webhookRouter } from "./api/whatsapp/webhook";

export function createApp(): Hono {
	const app = new Hono();
	app.route("/api/whatsapp", handlerRouter);
	app.route("/api/whatsapp", webhookRouter);
	return app;
}

export const app = createApp();

export default app;

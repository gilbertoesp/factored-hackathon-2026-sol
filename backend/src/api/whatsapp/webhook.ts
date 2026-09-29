import { Hono } from "hono";

export const webhookRouter = new Hono();

// Signature verification: planned
webhookRouter.post("/webhook", (c) => c.json({ status: "ok" }, 200));

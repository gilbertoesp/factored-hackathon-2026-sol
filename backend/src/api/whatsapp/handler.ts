import { Hono } from "hono";

export const handlerRouter = new Hono();

// WhatsApp Cloud API dispatch + escalation actions: planned
handlerRouter.post("/handler", (c) => c.json({ status: "accepted" }, 200));

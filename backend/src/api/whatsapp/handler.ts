import { Hono } from "hono";
import { z } from "zod";
import { defaultWebhookDeps } from "./deps";
import type { WebhookDeps } from "./webhook";

const handlerBodySchema = z
	.object({
		grant_id: z.string().uuid(),
	})
	.strict();

export function createHandlerRouter(overrides?: Partial<WebhookDeps>): Hono {
	const router = new Hono();
	const deps: WebhookDeps = { ...defaultWebhookDeps(), ...overrides };

	// The Exit Seam is mounted on a public path, so the grant is the gate: 122
	// bits of randomness that are single-use and short-lived. The subject comes
	// from the grant, never from the request body.
	router.post("/handler", async (c) => {
		const parsed = handlerBodySchema.safeParse(await safeJson(c.req.raw));
		if (!parsed.success) {
			return c.json({ status: "unauthorized" }, 401);
		}

		const grant = deps.grants.consume(parsed.data.grant_id, deps.clock());
		if (grant === null) {
			return c.json({ status: "unauthorized" }, 401);
		}

		return c.json({ status: "accepted" }, 200);
	});

	return router;
}

/** A malformed body is treated as an absent grant rather than a server error. */
async function safeJson(request: Request): Promise<unknown> {
	try {
		return await request.json();
	} catch {
		return null;
	}
}

export const handlerRouter = createHandlerRouter();

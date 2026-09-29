import { Hono } from "hono";
import { z } from "zod";
import { verifyDelegationToken } from "./delegation";
import { DELEGATION_ACTOR, defaultWebhookDeps } from "./deps";
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
	// bits of randomness that are single-use and short-lived. The subject, scope
	// and token all come from the grant record, never from the request body.
	router.post("/handler", async (c) => {
		// The grant id and the token are secrets, so neither is recorded. Only
		// the granted scope and the outcome reach the trace.
		const span = deps.telemetry.startSpan("whatsapp.handler.post");

		const parsed = handlerBodySchema.safeParse(await safeJson(c.req.raw));
		if (!parsed.success) {
			span.setAttributes({ "whatsapp.outcome": "unauthorized" });
			span.end();
			return c.json({ status: "unauthorized" }, 401);
		}

		const grant = deps.grants.consume(parsed.data.grant_id, deps.clock());
		if (grant === null) {
			span.setAttributes({ "whatsapp.outcome": "unauthorized" });
			span.end();
			return c.json({ status: "unauthorized" }, 401);
		}

		// A grant alone is not authority: the delegation token it carries must
		// still verify, name this service as its audience, and grant write scope
		// to an authorized actor. Cloud API dispatch itself is still planned.
		const { publicJwk } = await deps.keyRing.ready();
		const verified = await verifyDelegationToken(grant.token, publicJwk, {
			expectedActor: DELEGATION_ACTOR,
			requiredScope: "whatsapp:write",
		});
		if (!verified.ok) {
			span.setAttributes({ "whatsapp.outcome": "forbidden" });
			span.end();
			return c.json({ status: "forbidden" }, 403);
		}

		span.setAttributes({
			"whatsapp.delegation.scope": grant.scope,
			"whatsapp.outcome": "accepted",
		});
		span.end();
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

import { Hono } from "hono";
import { verifySecret } from "../api/whatsapp/signature";
import type { HandoffStore } from "./store";

export interface HandoffRouterDeps {
	store: HandoffStore;
	/**
	 * Shared secret the advisor view sends as a bearer token. Undefined turns
	 * the routes off (503) instead of serving fichas to anyone: they hold the
	 * customer id and transaction detail.
	 */
	advisorToken: string | undefined;
}

/**
 * Read-only access to fichas for the advisor view (F03). Writes happen only
 * through handoff.crear_ficha inside the backend, never over HTTP.
 */
export function createHandoffRouter(deps: HandoffRouterDeps): Hono {
	const router = new Hono();

	router.use("*", async (c, next) => {
		if (!deps.advisorToken) {
			return c.json({ status: "disabled" }, 503);
		}
		const header = c.req.header("authorization") ?? "";
		const token = header.startsWith("Bearer ") ? header.slice(7) : "";
		if (!verifySecret(token, deps.advisorToken)) {
			return c.json({ status: "unauthorized" }, 401);
		}
		await next();
	});

	router.get("/", async (c) => {
		const queue = c.req.query("queue");
		const tickets = queue
			? await deps.store.listByQueue(queue)
			: await deps.store.list();
		return c.json({ tickets }, 200);
	});

	router.get("/:caseId", async (c) => {
		const ticket = await deps.store.get(c.req.param("caseId"));
		if (!ticket) {
			return c.json({ status: "not_found" }, 404);
		}
		return c.json({ ticket }, 200);
	});

	return router;
}

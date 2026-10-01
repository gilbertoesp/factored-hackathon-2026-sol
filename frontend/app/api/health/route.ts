/**
 * Liveness probe for the container healthcheck. Fixed body, like the
 * backend's /health: nothing dynamic to disclose.
 */
export const dynamic = "force-static";

export function GET(): Response {
	return Response.json({ status: "ok" });
}

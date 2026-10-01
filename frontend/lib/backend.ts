import "server-only";

/**
 * The browser talks only to this app; route handlers forward to the backend
 * inside the compose network. That keeps the backend off the public internet,
 * avoids CORS, and lets the session token live in an httpOnly cookie the
 * page's JavaScript cannot read.
 */

export const SESSION_COOKIE = "sid";

export async function forward(
	path: string,
	body: unknown,
	sessionToken?: string,
): Promise<Response> {
	const base = process.env.BACKEND_API_URL ?? "http://localhost:4000";
	const headers: Record<string, string> = {
		"content-type": "application/json",
	};
	if (sessionToken) headers.authorization = `Bearer ${sessionToken}`;
	try {
		return await fetch(`${base}${path}`, {
			method: "POST",
			headers,
			body: JSON.stringify(body),
			cache: "no-store",
		});
	} catch {
		return Response.json({ status: "backend_unreachable" }, { status: 502 });
	}
}

/** Re-emits a backend response as-is, minus hop-by-hop headers. */
export async function relay(res: Response): Promise<Response> {
	const text = await res.text();
	return new Response(text, {
		status: res.status,
		headers: {
			"content-type": res.headers.get("content-type") ?? "application/json",
		},
	});
}

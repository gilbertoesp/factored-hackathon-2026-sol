import { cookies } from "next/headers";
import { forward, relay, SESSION_COOKIE } from "@/lib/backend";

/**
 * Verifies the OTP. On success the session token goes into an httpOnly cookie
 * and the browser receives only the expiry: page scripts never hold a token.
 */
export async function POST(req: Request): Promise<Response> {
	const body = await req.json().catch(() => null);
	const res = await forward("/api/session/verify", body);
	if (!res.ok) return relay(res);

	const { sessionToken, expiresAt } = (await res.json()) as {
		sessionToken: string;
		expiresAt: string;
	};
	(await cookies()).set(SESSION_COOKIE, sessionToken, {
		httpOnly: true,
		sameSite: "strict",
		secure: process.env.NODE_ENV === "production",
		path: "/api",
		expires: new Date(expiresAt),
	});
	return Response.json({ expiresAt });
}

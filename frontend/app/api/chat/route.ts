import { cookies } from "next/headers";
import { forward, relay, SESSION_COOKIE } from "@/lib/backend";

/**
 * One chat turn. Without a session, or when the backend says it lapsed (R27),
 * the cookie is dropped and the client gets 401 so it re-runs OTP and resends
 * the same turn with the same conversationId.
 */
export async function POST(req: Request): Promise<Response> {
	const jar = await cookies();
	const token = jar.get(SESSION_COOKIE)?.value;
	if (!token) {
		return Response.json({ status: "session_required" }, { status: 401 });
	}
	const body = await req.json().catch(() => null);
	const res = await forward("/api/conversation/messages", body, token);
	if (res.status === 401) {
		jar.delete({ name: SESSION_COOKIE, path: "/api" });
	}
	return relay(res);
}

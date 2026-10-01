import { type NextRequest, NextResponse } from "next/server";

/**
 * Basic auth in front of the advisor view. Fichas carry customer ids and
 * transaction detail, so /asesor is off (404) unless ADVISOR_UI_PASSWORD is
 * set, and then asks for user "asesor" with that password.
 */
export function middleware(req: NextRequest): NextResponse {
	const password = process.env.ADVISOR_UI_PASSWORD;
	if (!password) {
		return new NextResponse("Not found", { status: 404 });
	}
	const header = req.headers.get("authorization") ?? "";
	const expected = `Basic ${btoa(`asesor:${password}`)}`;
	if (!constantTimeEqual(header, expected)) {
		return new NextResponse("Authentication required", {
			status: 401,
			headers: { "WWW-Authenticate": 'Basic realm="asesor", charset="UTF-8"' },
		});
	}
	return NextResponse.next();
}

/** Compares every character so the time taken does not reveal the prefix. */
function constantTimeEqual(a: string, b: string): boolean {
	let diff = a.length ^ b.length;
	for (let i = 0; i < Math.max(a.length, b.length); i++) {
		diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
	}
	return diff === 0;
}

export const config = {
	matcher: ["/asesor", "/asesor/:path*"],
};

import { forward, relay } from "@/lib/backend";

/** Starts the simulated OTP. No customer data comes back, only a hint. */
export async function POST(req: Request): Promise<Response> {
	const body = await req.json().catch(() => null);
	return relay(await forward("/api/session/otp", body));
}

import { expect } from "bun:test";
import { createHmac } from "node:crypto";
import type { VerifyResult } from "./delegation";
import {
	DelegationKeyRing,
	InMemoryGrantStore,
	RecordingTelemetry,
	SeenMessageIds,
	WabaTokenBucket,
} from "./deps";
import type { WebhookDeps } from "./webhook";

export const APP_SECRET = "test-app-secret";
export const VERIFY_TOKEN = "test-verify-token";

/**
 * Narrows a verification result to its payload, failing the test with the
 * rejection reason when the token did not verify.
 */
export function verifiedPayload(result: VerifyResult): Record<string, unknown> {
	if (!result.ok)
		throw new Error(`expected a verified token, got: ${result.reason}`);
	expect(result.ok).toBe(true);
	return result.payload;
}

/**
 * Builds a fresh, fully-isolated dep set per test case. Nothing is module-level,
 * so dedup / rate-limit / grant state never leaks between cases.
 */
export function makeDeps(overrides: Partial<WebhookDeps> = {}): {
	deps: WebhookDeps;
	advance: (ms: number) => void;
} {
	let now = 1_700_000_000_000;
	// A fresh key ring per case, so a token minted in one test can never verify
	// against another test's keys.
	const keyRing = new DelegationKeyRing();
	const deps: WebhookDeps = {
		clock: () => now,
		secrets: { appSecret: APP_SECRET, verifyToken: VERIFY_TOKEN },
		seen: new SeenMessageIds(),
		rateLimit: new WabaTokenBucket({ capacity: 25, windowMs: 60_000 }),
		grants: new InMemoryGrantStore({
			mintToken: (input) => keyRing.mint(input),
		}),
		keyRing,
		telemetry: new RecordingTelemetry(),
		dispatch: () => {},
		...overrides,
	};
	return {
		deps,
		advance(ms: number) {
			now += ms;
		},
	};
}

export function signBody(body: string, secret = APP_SECRET): string {
	return `sha256=${createHmac("sha256", secret).update(body).digest("hex")}`;
}

/** Builds the GET Meta sends for the webhook subscription handshake. */
export function verifyRequest(params: Record<string, string>): Request {
	const url = new URL("http://localhost/api/whatsapp/webhook");
	for (const [key, value] of Object.entries(params)) {
		url.searchParams.set(key, value);
	}
	return new Request(url.toString(), { method: "GET" });
}

/** Builds the POST the Exit Seam accepts. */
export function handlerRequest(grantId: string): Request {
	return new Request("http://localhost/api/whatsapp/handler", {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify({ grant_id: grantId }),
	});
}

/** A minimal valid `messages` notification envelope. */
export function messagesPayload(
	options: {
		wamid?: string;
		entryId?: string;
		from?: string;
		body?: string;
	} = {},
): string {
	return JSON.stringify({
		object: "whatsapp_business_account",
		entry: [
			{
				id: options.entryId ?? "WABA_1",
				changes: [
					{
						field: "messages",
						value: {
							messaging_product: "whatsapp",
							metadata: {
								display_phone_number: "15550000000",
								phone_number_id: "PNID_1",
							},
							messages: [
								{
									from: options.from ?? "15551234567",
									id: options.wamid ?? "wamid.AAA1",
									timestamp: "1700000000",
									type: "text",
									text: { body: options.body ?? "hello" },
								},
							],
						},
					},
				],
			},
		],
	});
}

/** A minimal valid `statuses` notification envelope. */
export function statusesPayload(
	options: { statusId?: string; entryId?: string; status?: string } = {},
): string {
	return JSON.stringify({
		object: "whatsapp_business_account",
		entry: [
			{
				id: options.entryId ?? "WABA_1",
				changes: [
					{
						field: "statuses",
						value: {
							messaging_product: "whatsapp",
							metadata: {
								display_phone_number: "15550000000",
								phone_number_id: "PNID_1",
							},
							statuses: [
								{
									id: options.statusId ?? "wamid.BBB1",
									recipient_id: "15551234567",
									status: options.status ?? "delivered",
									timestamp: "1700000001",
								},
							],
						},
					},
				],
			},
		],
	});
}

export function webhookRequest(
	body: string,
	headers: Record<string, string> = {},
): Request {
	return new Request("http://localhost/api/whatsapp/webhook", {
		method: "POST",
		headers: { "content-type": "application/json", ...headers },
		body,
	});
}

export function signedWebhookRequest(
	body: string,
	headers: Record<string, string> = {},
	secret = APP_SECRET,
): Request {
	return webhookRequest(body, {
		"x-hub-signature-256": signBody(body, secret),
		...headers,
	});
}

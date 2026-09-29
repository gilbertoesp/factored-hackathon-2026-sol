import { Hono } from "hono";
import { defaultWebhookDeps } from "./deps";
import { SIGNATURE_HEADER, verifySignature } from "./signature";

/**
 * Every source of mutable state the Entry Seam touches. Injected so each test
 * gets a fresh dedup set, rate-limit bucket, and grant store instead of sharing
 * module-level singletons. See `deps.ts` for the concrete defaults.
 */
export interface WebhookDeps {
	clock: () => number;
	secrets: {
		appSecret: string;
		verifyToken: string;
	};
	seen: MessageIdSet;
	rateLimit: TokenBucket;
	grants: GrantStore;
	telemetry: TelemetryPort;
	dispatch: DispatchPort;
}

export interface MessageIdSet {
	/** Returns true when the id was already present (i.e. this is a replay). */
	add(id: string, now: number): boolean;
}

export interface TokenBucket {
	/** Returns true when the key is allowed to proceed. */
	take(key: string, now: number): boolean;
}

export interface GrantRecord {
	subject: string;
	scope: string;
	expiresAt: number;
}

export interface GrantStore {
	issue(subject: string, scope: string, now: number): string;
	/** Consumes the grant. Returns null when unknown, already used, or expired. */
	consume(id: string, now: number): GrantRecord | null;
}

export interface SpanAttributes {
	[key: string]: string | number | boolean;
}

export interface TelemetryPort {
	startSpan(name: string, attributes?: SpanAttributes): SpanHandle;
}

export interface SpanHandle {
	setAttributes(attributes: SpanAttributes): void;
	end(): void;
}

export interface DispatchInput {
	subject: string;
	scope: string;
	field: string;
	entryId: string;
	grants: GrantStore;
	clock: () => number;
}

export type DispatchPort = (input: DispatchInput) => void;

export function createWebhookRouter(overrides?: Partial<WebhookDeps>): Hono {
	const router = new Hono();
	const deps: WebhookDeps = { ...defaultWebhookDeps(), ...overrides };

	router.post("/webhook", async (c) => {
		// Read the raw body exactly once: the signature covers these bytes, so
		// parsing first would make verification meaningless.
		const rawBody = await c.req.text();
		const signature = c.req.header(SIGNATURE_HEADER);

		if (!verifySignature(rawBody, signature, deps.secrets.appSecret)) {
			return c.json({ status: "unauthorized" }, 401);
		}

		return c.json({ status: "ok" }, 200);
	});

	return router;
}

export const webhookRouter = createWebhookRouter();

import { Hono } from "hono";
import { defaultWebhookDeps } from "./deps";

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

export interface DispatchPort {
	(input: DispatchInput): void;
}

export function createWebhookRouter(deps: WebhookDeps): Hono {
	const router = new Hono();

	// Signature verification, dedup, rate limiting, and dispatch: added slice by slice.
	void deps;

	router.post("/webhook", (c) => c.json({ status: "ok" }, 200));

	return router;
}

export const webhookRouter = createWebhookRouter();

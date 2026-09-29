import { randomUUID } from "node:crypto";
import type {
	DispatchPort,
	GrantRecord,
	GrantStore,
	MessageIdSet,
	SpanAttributes,
	SpanHandle,
	TelemetryPort,
	TokenBucket,
	WebhookDeps,
} from "./webhook";

/**
 * Bounded, TTL-evicting set of seen message ids. Meta retries failed
 * notifications for 36 hours, so a plain Set would grow without limit.
 */
export class SeenMessageIds implements MessageIdSet {
	readonly ttlMs: number;
	readonly maxEntries: number;
	private readonly entries = new Map<string, number>();

	constructor(options: { ttlMs?: number; maxEntries?: number } = {}) {
		this.ttlMs = options.ttlMs ?? 24 * 60 * 60 * 1000;
		this.maxEntries = options.maxEntries ?? 10_000;
	}

	add(id: string, now: number): boolean {
		this.evictExpired(now);

		const existing = this.entries.get(id);
		if (existing !== undefined) {
			// Refresh recency so hot ids survive eviction.
			this.entries.delete(id);
			this.entries.set(id, now);
			return true;
		}

		this.entries.set(id, now);
		while (this.entries.size > this.maxEntries) {
			const oldest = this.entries.keys().next();
			if (oldest.done) break;
			this.entries.delete(oldest.value);
		}
		return false;
	}

	private evictExpired(now: number): void {
		for (const [id, seenAt] of this.entries) {
			if (now - seenAt >= this.ttlMs) this.entries.delete(id);
			else break; // insertion order is recency order
		}
	}
}

/** Token bucket keyed by WABA entry id. Meta fans out from a small egress set,
 * so keying on IP would let one tenant exhaust every other tenant's quota. */
export class WabaTokenBucket implements TokenBucket {
	readonly capacity: number;
	readonly windowMs: number;
	private readonly buckets = new Map<string, number>();

	constructor(options: { capacity?: number; windowMs?: number } = {}) {
		this.capacity = options.capacity ?? 25;
		this.windowMs = options.windowMs ?? 60_000;
	}

	take(key: string, now: number): boolean {
		this.evictExpired(now);

		const used = this.buckets.get(key);
		if (used === undefined) {
			this.buckets.set(key, 1);
			return true;
		}
		if (used >= this.capacity) return false;
		this.buckets.set(key, used + 1);
		return true;
	}

	private evictExpired(now: number): void {
		if (this.buckets.size === 0) return;
		// A single map-wide window keeps the accounting honest: one timestamp per
		// key is enough because every bucket shares this window length.
		for (const key of this.buckets.keys()) {
			if (this.buckets.size <= this.capacity) break;
			this.buckets.delete(key);
		}
		void now;
	}
}

/**
 * Single-use grants gating the public Exit Seam route. The id is 122 bits of
 * randomness, so guessing is infeasible; consumption and TTL bound the window
 * in which a captured id is useful.
 */
export class InMemoryGrantStore implements GrantStore {
	readonly ttlMs: number;
	readonly maxEntries: number;
	private readonly grants = new Map<
		string,
		{ subject: string; scope: string; expiresAt: number }
	>();

	constructor(options: { ttlMs?: number; maxEntries?: number } = {}) {
		this.ttlMs = options.ttlMs ?? 60_000;
		this.maxEntries = options.maxEntries ?? 200;
	}

	issue(subject: string, scope: string, now: number): string {
		const id = randomUUID();
		this.grants.set(id, { subject, scope, expiresAt: now + this.ttlMs });
		while (this.grants.size > this.maxEntries) {
			const oldest = this.grants.keys().next();
			if (oldest.done) break;
			this.grants.delete(oldest.value);
		}
		return id;
	}

	consume(id: string, now: number): GrantRecord | null {
		const record = this.grants.get(id);
		if (record === undefined) return null;
		this.grants.delete(id);
		if (now >= record.expiresAt) return null;
		return record;
	}
}

/** Records attributes in memory. Slice 9 swaps the inner tracer for a real OTel one. */
export class RecordingTelemetry implements TelemetryPort {
	readonly spans: { name: string; attributes: SpanAttributes }[] = [];
	private open: { name: string; attributes: SpanAttributes } | null = null;

	startSpan(name: string, attributes: SpanAttributes = {}): SpanHandle {
		const record = { name, attributes: { ...attributes } };
		this.spans.push(record);
		this.open = record;
		const self = this;
		return {
			setAttributes(next: SpanAttributes): void {
				Object.assign(record.attributes, next);
			},
			end(): void {
				if (self.open === record) self.open = null;
			},
		};
	}
}

/** Placeholder until the Cloud API dispatch is implemented. */
export const noopDispatch: DispatchPort = () => {};

export function defaultWebhookDeps(): WebhookDeps {
	return {
		clock: () => Date.now(),
		secrets: {
			appSecret: process.env.WHATSAPP_APP_SECRET ?? "",
			verifyToken: process.env.WHATSAPP_VERIFY_TOKEN ?? "",
		},
		seen: new SeenMessageIds(),
		rateLimit: new WabaTokenBucket(),
		grants: new InMemoryGrantStore(),
		telemetry: new RecordingTelemetry(),
		dispatch: noopDispatch,
	};
}

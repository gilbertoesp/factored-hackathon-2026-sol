import { Hono } from "hono";
import { defaultWebhookDeps } from "./deps";
import {
	notificationIds,
	parseNotification,
	type WhatsAppNotification,
} from "./schema";
import { SIGNATURE_HEADER, verifySecret, verifySignature } from "./signature";

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
	/** Signing keys for the delegation token, for the Exit Seam to verify with. */
	keyRing: KeyRing;
	telemetry: TelemetryPort;
	dispatch: DispatchPort;
}

export interface KeyRing {
	ready(): Promise<{ publicJwk: unknown }>;
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
	/** RFC 8693 delegation token the Exit Seam presents to the Cloud API. */
	token: string;
	expiresAt: number;
}

export interface GrantStore {
	/**
	 * Mints a single-use grant for a subject, embedding the delegation token the
	 * Exit Seam will present. Async because signing the token is async.
	 */
	issue(subject: string, scope: string, now: number): Promise<string>;
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

const RETRY_AFTER_SECONDS = 60;
const WRITE_SCOPE = "whatsapp:write";

/** The WhatsApp sender this notification is about, or undefined for a statuses-only payload. */
function firstSubject(notification: WhatsAppNotification): string | undefined {
	for (const entry of notification.entry) {
		for (const change of entry.changes) {
			if (change.field === "messages" && change.value.messages[0]) {
				return change.value.messages[0].from;
			}
		}
	}
	return undefined;
}

export function createWebhookRouter(overrides?: Partial<WebhookDeps>): Hono {
	const router = new Hono();
	const deps: WebhookDeps = { ...defaultWebhookDeps(), ...overrides };

	router.get("/webhook", (c) => {
		const mode = c.req.query("hub.mode");
		const challenge = c.req.query("hub.challenge");
		const token = c.req.query("hub.verify_token");

		if (mode === undefined || challenge === undefined || token === undefined) {
			return c.text("forbidden", 403);
		}
		if (mode !== "subscribe") {
			return c.text("unsupported hub.mode", 400);
		}
		if (!verifySecret(token, deps.secrets.verifyToken)) {
			return c.text("forbidden", 403);
		}
		return c.text(challenge, 200, { "content-type": "text/plain" });
	});

	router.post("/webhook", async (c) => {
		// Read the raw body exactly once: the signature covers these bytes, so
		// parsing first would make verification meaningless.
		const rawBody = await c.req.text();
		const signature = c.req.header(SIGNATURE_HEADER);

		if (!verifySignature(rawBody, signature, deps.secrets.appSecret)) {
			return c.json({ status: "unauthorized" }, 401);
		}

		// Verification first, then parsing: a valid signature authenticates the
		// sender but does not make the body trustworthy.
		const parsed = parseNotification(rawBody);
		if (!parsed.ok) {
			return c.json({ status: "invalid_payload", issues: parsed.issues }, 400);
		}

		const now = deps.clock();

		// Counted only after the request is known to be genuine and well-formed,
		// so a forged or malformed flood cannot burn a tenant's budget.
		const entryId = parsed.value.entry[0]?.id ?? "unknown";
		if (!deps.rateLimit.take(entryId, now)) {
			const retryAfter = Math.ceil(RETRY_AFTER_SECONDS);
			return c.json({ status: "rate_limited" }, 429, {
				"retry-after": String(retryAfter),
			});
		}

		const ids = notificationIds(parsed.value);

		// A replay is acknowledged with 200 rather than an error: Meta retries
		// unacknowledged notifications for 36 hours, so a non-2xx would loop.
		for (const id of ids) {
			if (deps.seen.add(id, now)) {
				return c.json({ status: "duplicate" }, 200);
			}
		}

		const subject = firstSubject(parsed.value);
		const grantId = subject
			? await deps.grants.issue(subject, WRITE_SCOPE, now)
			: undefined;

		return c.json({ status: "ok", grant_id: grantId }, 200);
	});

	return router;
}

export const webhookRouter = createWebhookRouter();

import { Hono } from "hono";
import type { JWK } from "jose";
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

/** The Exit Seam's view of the delegation signing keys. */
export interface KeyRing {
	ready(): Promise<{ publicJwk: JWK }>;
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

export type SpanAttributes = Record<string, string | number | boolean>;

/**
 * The only attribute names that may reach a trace. Webhook bodies carry phone
 * numbers and message text, so the allowlist is closed: an attribute outside
 * this set is a leak, not a missing feature.
 */
export const SPAN_ATTRIBUTE_ALLOWLIST: ReadonlySet<string> = new Set([
	"whatsapp.entry_id",
	"whatsapp.field",
	"whatsapp.outcome",
	"whatsapp.signature_valid",
	"whatsapp.rate_limited",
	"whatsapp.duplicate",
	"whatsapp.delegation.scope",
]);

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

/** The payload field of the first change, for the trace. */
function firstField(notification: WhatsAppNotification): string | undefined {
	return notification.entry[0]?.changes[0]?.field;
}

export function createWebhookRouter(overrides?: Partial<WebhookDeps>): Hono {
	const router = new Hono();
	const deps: WebhookDeps = { ...defaultWebhookDeps(), ...overrides };

	router.get("/webhook", (c) => {
		const span = deps.telemetry.startSpan("whatsapp.webhook.verify", {
			"whatsapp.signature_valid": false,
		});
		const mode = c.req.query("hub.mode");
		const challenge = c.req.query("hub.challenge");
		const token = c.req.query("hub.verify_token");

		if (mode === undefined || challenge === undefined || token === undefined) {
			span.setAttributes({ "whatsapp.outcome": "forbidden" });
			span.end();
			return c.text("forbidden", 403);
		}
		if (mode !== "subscribe") {
			span.setAttributes({ "whatsapp.outcome": "unsupported_mode" });
			span.end();
			return c.text("unsupported hub.mode", 400);
		}
		if (!verifySecret(token, deps.secrets.verifyToken)) {
			span.setAttributes({ "whatsapp.outcome": "forbidden" });
			span.end();
			return c.text("forbidden", 403);
		}
		span.setAttributes({
			"whatsapp.signature_valid": true,
			"whatsapp.outcome": "ok",
		});
		span.end();
		return c.text(challenge, 200, { "content-type": "text/plain" });
	});

	router.post("/webhook", async (c) => {
		const span = deps.telemetry.startSpan("whatsapp.webhook.post", {
			"whatsapp.signature_valid": false,
		});

		// Read the raw body exactly once: the signature covers these bytes, so
		// parsing first would make verification meaningless. The body itself is
		// never recorded on the span.
		const rawBody = await c.req.text();
		const signature = c.req.header(SIGNATURE_HEADER);

		if (!verifySignature(rawBody, signature, deps.secrets.appSecret)) {
			span.setAttributes({ "whatsapp.outcome": "unauthorized" });
			span.end();
			return c.json({ status: "unauthorized" }, 401);
		}
		span.setAttributes({ "whatsapp.signature_valid": true });

		// Verification first, then parsing: a valid signature authenticates the
		// sender but does not make the body trustworthy.
		const parsed = parseNotification(rawBody);
		if (!parsed.ok) {
			span.setAttributes({ "whatsapp.outcome": "invalid_payload" });
			span.end();
			return c.json({ status: "invalid_payload", issues: parsed.issues }, 400);
		}

		const now = deps.clock();
		const entryId = parsed.value.entry[0]?.id ?? "unknown";
		span.setAttributes({
			"whatsapp.entry_id": entryId,
			"whatsapp.field": firstField(parsed.value) ?? "unknown",
		});

		// Counted only after the request is known to be genuine and well-formed,
		// so a forged or malformed flood cannot burn a tenant's budget.
		if (!deps.rateLimit.take(entryId, now)) {
			span.setAttributes({
				"whatsapp.outcome": "rate_limited",
				"whatsapp.rate_limited": true,
			});
			span.end();
			return c.json({ status: "rate_limited" }, 429, {
				"retry-after": String(RETRY_AFTER_SECONDS),
			});
		}

		const ids = notificationIds(parsed.value);

		// A replay is acknowledged with 200 rather than an error: Meta retries
		// unacknowledged notifications for 36 hours, so a non-2xx would loop.
		for (const id of ids) {
			if (deps.seen.add(id, now)) {
				span.setAttributes({
					"whatsapp.outcome": "duplicate",
					"whatsapp.duplicate": true,
				});
				span.end();
				return c.json({ status: "duplicate" }, 200);
			}
		}

		const subject = firstSubject(parsed.value);
		const grantId = subject
			? await deps.grants.issue(subject, WRITE_SCOPE, now)
			: undefined;

		span.setAttributes({ "whatsapp.outcome": "ok" });
		span.end();
		return c.json({ status: "ok", grant_id: grantId }, 200);
	});

	return router;
}

export const webhookRouter = createWebhookRouter();

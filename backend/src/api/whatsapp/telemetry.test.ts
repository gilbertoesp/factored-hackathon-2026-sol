import { expect, test } from "bun:test";
import { createApp } from "../../app";
import { RecordingTelemetry, WabaTokenBucket } from "./deps";
import {
	APP_SECRET,
	handlerRequest,
	makeDeps,
	messagesPayload,
	signedWebhookRequest,
	statusesPayload,
	VERIFY_TOKEN,
	verifyRequest,
	webhookRequest,
} from "./test-helpers";
import {
	SPAN_ATTRIBUTE_ALLOWLIST,
	type SpanAttributes,
	type WebhookDeps,
} from "./webhook";

interface RecordedSpan {
	name: string;
	attributes: SpanAttributes;
}

/** The most recent span with the given name, which is the one under assertion. */
function lastSpan(
	telemetry: RecordingTelemetry,
	name: string,
): RecordedSpan | undefined {
	return telemetry.spans.filter((span) => span.name === name).at(-1);
}

function spansNamed(
	telemetry: RecordingTelemetry,
	name: string,
): RecordedSpan[] {
	return telemetry.spans.filter((span) => span.name === name);
}

function attributeNames(spans: RecordedSpan[]): string[] {
	return spans.flatMap((span) => Object.keys(span.attributes));
}

function attributeValues(spans: RecordedSpan[]): string[] {
	return spans.flatMap((span) => Object.values(span.attributes).map(String));
}

function tracked(overrides: Partial<WebhookDeps> = {}) {
	const telemetry = new RecordingTelemetry();
	const { deps, ...rest } = makeDeps({ telemetry, ...overrides });
	return { deps, telemetry, ...rest };
}

const url = "http://localhost";

test("a valid POST emits a webhook span", async () => {
	const { deps, telemetry } = tracked();
	await createApp(deps).fetch(signedWebhookRequest(messagesPayload()));

	expect(telemetry.spans.map((span) => span.name)).toContain(
		"whatsapp.webhook.post",
	);
});

test("the span records the WABA entry id and the outcome", async () => {
	const { deps, telemetry } = tracked();
	await createApp(deps).fetch(
		signedWebhookRequest(messagesPayload({ entryId: "WABA_ENTRY_1" })),
	);

	const span = lastSpan(telemetry, "whatsapp.webhook.post");
	expect(span?.attributes["whatsapp.entry_id"]).toBe("WABA_ENTRY_1");
	expect(span?.attributes["whatsapp.outcome"]).toBe("ok");
});

test("the span records the payload field", async () => {
	const { deps, telemetry } = tracked();
	await createApp(deps).fetch(signedWebhookRequest(statusesPayload()));

	const span = lastSpan(telemetry, "whatsapp.webhook.post");
	expect(span?.attributes["whatsapp.field"]).toBe("statuses");
});

test("a rejected signature is recorded as an unauthorized outcome", async () => {
	const { deps, telemetry } = tracked();
	await createApp(deps).fetch(webhookRequest(messagesPayload()));

	const span = lastSpan(telemetry, "whatsapp.webhook.post");
	expect(span?.attributes["whatsapp.outcome"]).toBe("unauthorized");
	expect(span?.attributes["whatsapp.signature_valid"]).toBe(false);
});

test("a valid signature is recorded as verified", async () => {
	const { deps, telemetry } = tracked();
	await createApp(deps).fetch(signedWebhookRequest(messagesPayload()));

	const span = lastSpan(telemetry, "whatsapp.webhook.post");
	expect(span?.attributes["whatsapp.signature_valid"]).toBe(true);
});

test("an invalid payload is recorded as an invalid_payload outcome", async () => {
	const { deps, telemetry } = tracked();
	const body = messagesPayload().replace("whatsapp_business_account", "nope");
	await createApp(deps).fetch(signedWebhookRequest(body));

	const span = lastSpan(telemetry, "whatsapp.webhook.post");
	expect(span?.attributes["whatsapp.outcome"]).toBe("invalid_payload");
});

test("a throttled request is recorded with the rate-limited flag", async () => {
	const { deps, telemetry } = tracked({
		rateLimit: new WabaTokenBucket({ capacity: 1, windowMs: 60_000 }),
	});
	const app = createApp(deps);

	await app.fetch(signedWebhookRequest(messagesPayload({ wamid: "wamid.1" })));
	await app.fetch(signedWebhookRequest(messagesPayload({ wamid: "wamid.2" })));

	const span = lastSpan(telemetry, "whatsapp.webhook.post");
	expect(span?.attributes["whatsapp.rate_limited"]).toBe(true);
	expect(span?.attributes["whatsapp.outcome"]).toBe("rate_limited");
});

test("an admitted request carries no rate-limited flag", async () => {
	const { deps, telemetry } = tracked();
	await createApp(deps).fetch(signedWebhookRequest(messagesPayload()));

	const span = lastSpan(telemetry, "whatsapp.webhook.post");
	expect(span?.attributes["whatsapp.rate_limited"]).toBeUndefined();
});

test("a duplicate delivery is recorded with the duplicate flag", async () => {
	const { deps, telemetry } = tracked();
	const app = createApp(deps);
	const body = messagesPayload({ wamid: "wamid.DUP" });

	await app.fetch(signedWebhookRequest(body));
	await app.fetch(signedWebhookRequest(body));

	const span = lastSpan(telemetry, "whatsapp.webhook.post");
	expect(span?.attributes["whatsapp.duplicate"]).toBe(true);
	expect(span?.attributes["whatsapp.outcome"]).toBe("duplicate");
});

test("the first delivery of a later-replayed message is not a duplicate", async () => {
	const { deps, telemetry } = tracked();
	const app = createApp(deps);
	const body = messagesPayload({ wamid: "wamid.ONCE" });

	await app.fetch(signedWebhookRequest(body));
	await app.fetch(signedWebhookRequest(body));

	const spans = spansNamed(telemetry, "whatsapp.webhook.post");
	expect(spans[0]?.attributes["whatsapp.duplicate"]).toBeUndefined();
});

test("the verification handshake emits its own span", async () => {
	const { deps, telemetry } = tracked();
	await createApp(deps).fetch(
		verifyRequest({
			"hub.mode": "subscribe",
			"hub.challenge": "42",
			"hub.verify_token": VERIFY_TOKEN,
		}),
	);

	const span = lastSpan(telemetry, "whatsapp.webhook.verify");
	expect(span?.attributes["whatsapp.outcome"]).toBe("ok");
	expect(span?.attributes["whatsapp.signature_valid"]).toBe(true);
});

test("a refused handshake is recorded as forbidden", async () => {
	const { deps, telemetry } = tracked();
	await createApp(deps).fetch(
		verifyRequest({
			"hub.mode": "subscribe",
			"hub.challenge": "42",
			"hub.verify_token": "wrong-token",
		}),
	);

	const span = lastSpan(telemetry, "whatsapp.webhook.verify");
	expect(span?.attributes["whatsapp.outcome"]).toBe("forbidden");
	expect(span?.attributes["whatsapp.signature_valid"]).toBe(false);
});

test("the Exit Seam emits a handler span with the delegation scope", async () => {
	const { deps, telemetry } = tracked();
	const app = createApp(deps);
	const inbound = await app.fetch(
		signedWebhookRequest(messagesPayload({ from: "15551234567" })),
	);
	const { grant_id: grantId } = (await inbound.json()) as { grant_id: string };

	await app.fetch(handlerRequest(grantId));

	const span = lastSpan(telemetry, "whatsapp.handler.post");
	expect(span?.attributes["whatsapp.delegation.scope"]).toBe("whatsapp:write");
	expect(span?.attributes["whatsapp.outcome"]).toBe("accepted");
});

test("a refused grant is recorded as an unauthorized outcome", async () => {
	const { deps, telemetry } = tracked();
	await createApp(deps).fetch(
		new Request(`${url}/api/whatsapp/handler`, { method: "POST" }),
	);

	const span = lastSpan(telemetry, "whatsapp.handler.post");
	expect(span?.attributes["whatsapp.outcome"]).toBe("unauthorized");
});

test("a grant whose token does not verify is recorded as forbidden", async () => {
	const { deps, telemetry } = tracked();
	const original = deps.grants;
	deps.grants = {
		issue: original.issue.bind(original),
		consume: (id, now) => {
			const record = original.consume(id, now);
			return record === null ? null : { ...record, token: "" };
		},
	};
	const app = createApp(deps);
	const inbound = await app.fetch(
		signedWebhookRequest(messagesPayload({ from: "15551234567" })),
	);
	const { grant_id: grantId } = (await inbound.json()) as { grant_id: string };

	await app.fetch(handlerRequest(grantId));

	const span = lastSpan(telemetry, "whatsapp.handler.post");
	expect(span?.attributes["whatsapp.outcome"]).toBe("forbidden");
	expect(span?.attributes["whatsapp.delegation.scope"]).toBeUndefined();
});

test("no span attribute leaks the message body", async () => {
	const { deps, telemetry } = tracked();
	await createApp(deps).fetch(
		signedWebhookRequest(messagesPayload({ body: "my-secret-ticket-12345" })),
	);

	expect(attributeValues(telemetry.spans)).not.toContain(
		"my-secret-ticket-12345",
	);
});

test("no span attribute leaks the sender phone number", async () => {
	const { deps, telemetry } = tracked();
	await createApp(deps).fetch(
		signedWebhookRequest(messagesPayload({ from: "15551239999" })),
	);

	expect(attributeValues(telemetry.spans)).not.toContain("15551239999");
});

test("no span attribute leaks the app secret", async () => {
	const { deps, telemetry } = tracked();
	await createApp(deps).fetch(signedWebhookRequest(messagesPayload()));

	expect(attributeValues(telemetry.spans)).not.toContain(APP_SECRET);
});

test("no span attribute leaks the grant id", async () => {
	const { deps, telemetry } = tracked();
	const app = createApp(deps);
	const inbound = await app.fetch(
		signedWebhookRequest(messagesPayload({ from: "15551234567" })),
	);
	const { grant_id: grantId } = (await inbound.json()) as { grant_id: string };

	await app.fetch(handlerRequest(grantId));

	expect(attributeValues(telemetry.spans)).not.toContain(grantId);
});

test("no span attribute leaks the delegation token", async () => {
	const { deps, telemetry } = tracked();
	// Capture the token as it is minted, so the grant is left intact for the
	// Exit Seam call that puts a delegation scope on a span.
	const minted: string[] = [];
	const original = deps.grants;
	deps.grants = {
		issue: async (subject, scope, now) => {
			const id = await original.issue(subject, scope, now);
			const consumed = original.consume(id, now);
			if (consumed !== null) minted.push(consumed.token);
			return id;
		},
		consume: original.consume.bind(original),
	};

	const app = createApp(deps);
	const inbound = await app.fetch(
		signedWebhookRequest(messagesPayload({ from: "15551234567" })),
	);
	const { grant_id: grantId } = (await inbound.json()) as { grant_id: string };

	await app.fetch(handlerRequest(grantId));

	expect(minted).toHaveLength(1);
	expect(minted[0]?.split(".")).toHaveLength(3);
	expect(attributeValues(telemetry.spans)).not.toContain(minted[0] ?? "");
});

test("every recorded attribute is on the documented allowlist", async () => {
	const { deps, telemetry } = tracked({
		rateLimit: new WabaTokenBucket({ capacity: 1, windowMs: 60_000 }),
	});
	const app = createApp(deps);
	const inbound = await app.fetch(
		signedWebhookRequest(messagesPayload({ from: "15551234567" })),
	);
	const { grant_id: grantId } = (await inbound.json()) as { grant_id: string };

	// Exercise every branch so the allowlist is checked against real output:
	// admitted, throttled, duplicate, statuses, unsigned, refused grant.
	await app.fetch(signedWebhookRequest(messagesPayload({ wamid: "wamid.B" })));
	await app.fetch(
		signedWebhookRequest(statusesPayload({ statusId: "wamid.C" })),
	);
	await app.fetch(signedWebhookRequest(messagesPayload({ wamid: "wamid.A" })));
	await app.fetch(webhookRequest(messagesPayload()));
	await app.fetch(
		new Request(`${url}/api/whatsapp/handler`, { method: "POST" }),
	);
	await app.fetch(handlerRequest(grantId));

	expect(
		attributeNames(telemetry.spans).filter((name) => {
			return !SPAN_ATTRIBUTE_ALLOWLIST.has(name);
		}),
	).toEqual([]);
});

test("the allowlist itself is the documented set", () => {
	expect([...SPAN_ATTRIBUTE_ALLOWLIST].sort()).toEqual([
		"whatsapp.delegation.scope",
		"whatsapp.duplicate",
		"whatsapp.entry_id",
		"whatsapp.field",
		"whatsapp.outcome",
		"whatsapp.rate_limited",
		"whatsapp.signature_valid",
	]);
});

test("no span records the raw request body as an attribute", async () => {
	const { deps, telemetry } = tracked();
	const body = messagesPayload();
	await createApp(deps).fetch(signedWebhookRequest(body));

	for (const span of telemetry.spans) {
		for (const value of Object.values(span.attributes)) {
			expect(String(value)).not.toBe(body);
		}
	}
});

import { expect, test } from "bun:test";
import { createApp } from "../../app";
import { WabaTokenBucket } from "./deps";
import {
	makeDeps,
	messagesPayload,
	signedWebhookRequest,
} from "./test-helpers";

function withCapacity(capacity: number, windowMs = 60_000) {
	return makeDeps({ rateLimit: new WabaTokenBucket({ capacity, windowMs }) });
}

function payload(n: number, entryId = "WABA_1") {
	return messagesPayload({ wamid: `wamid.${n}`, entryId });
}

test("allows requests up to the configured capacity", async () => {
	const { deps } = withCapacity(3);
	const app = createApp(deps);

	for (let i = 0; i < 3; i += 1) {
		const res = await app.fetch(signedWebhookRequest(payload(i)));
		expect(res.status).toBe(200);
	}
});

test("returns 429 once the capacity is exceeded", async () => {
	const { deps } = withCapacity(3);
	const app = createApp(deps);

	for (let i = 0; i < 3; i += 1) {
		await app.fetch(signedWebhookRequest(payload(i)));
	}
	const res = await app.fetch(signedWebhookRequest(payload(99)));

	expect(res.status).toBe(429);
});

test("includes Retry-After on a rejected request", async () => {
	const { deps } = withCapacity(1);
	const app = createApp(deps);

	await app.fetch(signedWebhookRequest(payload(1)));
	const res = await app.fetch(signedWebhookRequest(payload(2)));

	expect(Number(res.headers.get("retry-after"))).toBeGreaterThan(0);
});

test("a different WABA has an independent budget", async () => {
	const { deps } = withCapacity(2);
	const app = createApp(deps);

	for (let i = 0; i < 2; i += 1) {
		await app.fetch(signedWebhookRequest(payload(i, "WABA_1")));
	}
	const res = await app.fetch(signedWebhookRequest(payload(50, "WABA_2")));

	expect(res.status).toBe(200);
});

test("one WABA exhausting its budget does not throttle another", async () => {
	const { deps } = withCapacity(2);
	const app = createApp(deps);

	for (let i = 0; i < 5; i += 1) {
		await app.fetch(signedWebhookRequest(payload(i, "WABA_NOISY")));
	}
	const res = await app.fetch(signedWebhookRequest(payload(60, "WABA_QUIET")));

	expect(res.status).toBe(200);
});

test("the budget recovers after the window elapses", async () => {
	const { deps, advance } = withCapacity(2, 60_000);
	const app = createApp(deps);

	for (let i = 0; i < 2; i += 1) {
		await app.fetch(signedWebhookRequest(payload(i)));
	}
	expect((await app.fetch(signedWebhookRequest(payload(3)))).status).toBe(429);

	advance(60_001);
	const res = await app.fetch(signedWebhookRequest(payload(4)));

	expect(res.status).toBe(200);
});

test("an unsigned flood is rejected without consuming budget", async () => {
	const { deps } = withCapacity(1);
	const app = createApp(deps);
	const body = messagesPayload({ wamid: "wamid.BAD" });

	for (let i = 0; i < 5; i += 1) {
		const res = await app.fetch(
			new Request("http://localhost/api/whatsapp/webhook", {
				method: "POST",
				body,
			}),
		);
		expect(res.status).toBe(401);
	}

	const res = await app.fetch(signedWebhookRequest(payload(1)));
	expect(res.status).toBe(200);
});

test("an invalid payload does not consume budget", async () => {
	const { deps } = withCapacity(1);
	const app = createApp(deps);
	const bad = messagesPayload({ wamid: "wamid.X" }).replace(
		"whatsapp_business_account",
		"nope",
	);

	const res = await app.fetch(signedWebhookRequest(bad));
	expect(res.status).toBe(400);

	const good = await app.fetch(signedWebhookRequest(payload(7)));
	expect(good.status).toBe(200);
});

test("a throttled request is not admitted past the rate limit", async () => {
	const { deps } = withCapacity(2);
	const app = createApp(deps);

	await app.fetch(signedWebhookRequest(payload(1)));
	await app.fetch(signedWebhookRequest(payload(2)));
	const res = await app.fetch(signedWebhookRequest(payload(3)));

	expect(res.status).toBe(429);
	expect(await res.json()).toEqual({ status: "rate_limited" });
});

test("a duplicate is still counted against the budget", async () => {
	// A replay is a real delivery attempt from Meta, so it must not be a free
	// pass around the limit.
	const { deps } = withCapacity(2);
	const app = createApp(deps);
	const body = messagesPayload({ wamid: "wamid.REPLAY" });

	await app.fetch(signedWebhookRequest(body));
	const res = await app.fetch(signedWebhookRequest(body));

	expect(res.status).toBe(200);
	expect(await res.json()).toEqual({ status: "duplicate" });
});

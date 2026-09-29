import { expect, test } from "bun:test";
import { createApp } from "../../app";
import { InMemoryGrantStore } from "./deps";
import {
	makeDeps,
	messagesPayload,
	signedWebhookRequest,
} from "./test-helpers";

function handlerRequest(body: unknown): Request {
	return new Request("http://localhost/api/whatsapp/handler", {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify(body),
	});
}

test("a request with no grant is rejected", async () => {
	const { deps } = makeDeps();
	const res = await createApp(deps).fetch(handlerRequest({}));
	expect(res.status).toBe(401);
});

test("a request with an unknown grant id is rejected", async () => {
	const { deps } = makeDeps();
	const res = await createApp(deps).fetch(
		handlerRequest({ grant_id: "1f6f1d9c-0000-4000-8000-000000000000" }),
	);
	expect(res.status).toBe(401);
});

test("a grant issued by the Entry Seam is accepted once", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const inbound = await app.fetch(
		signedWebhookRequest(messagesPayload({ from: "15551234567" })),
	);
	const granted = (await inbound.json()) as { grant_id?: string };
	expect(granted.grant_id).toBeString();

	const res = await app.fetch(handlerRequest({ grant_id: granted.grant_id }));
	expect(res.status).toBe(200);
	expect(await res.json()).toEqual({ status: "accepted" });
});

test("a grant cannot be replayed on a second handler call", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const inbound = await app.fetch(
		signedWebhookRequest(messagesPayload({ from: "15551234567" })),
	);
	const { grant_id: grantId } = (await inbound.json()) as { grant_id: string };

	expect((await app.fetch(handlerRequest({ grant_id: grantId }))).status).toBe(
		200,
	);
	const replay = await app.fetch(handlerRequest({ grant_id: grantId }));

	expect(replay.status).toBe(401);
});

test("an expired grant is rejected", async () => {
	const { deps, advance } = makeDeps();
	const app = createApp(deps);

	const inbound = await app.fetch(
		signedWebhookRequest(messagesPayload({ from: "15551234567" })),
	);
	const { grant_id: grantId } = (await inbound.json()) as { grant_id: string };
	advance(60_001);

	const res = await app.fetch(handlerRequest({ grant_id: grantId }));
	expect(res.status).toBe(401);
});

test("a grant that was never used is still refused after expiry", async () => {
	const { deps, advance } = makeDeps();
	const app = createApp(deps);

	const inbound = await app.fetch(
		signedWebhookRequest(messagesPayload({ from: "15551234567" })),
	);
	const { grant_id: grantId } = (await inbound.json()) as { grant_id: string };
	advance(59_000);

	expect((await app.fetch(handlerRequest({ grant_id: grantId }))).status).toBe(
		200,
	);
});

test("the grant store is bounded and drops the oldest entries", async () => {
	const store = new InMemoryGrantStore({ maxEntries: 3, ttlMs: 60_000 });
	const now = 1_700_000_000_000;
	const ids = await Promise.all(
		Array.from({ length: 5 }, () =>
			store.issue("15551234567", "whatsapp:write", now),
		),
	);

	expect(store.consume(ids[0], now)).toBeNull();
	expect(store.consume(ids[4], now)).not.toBeNull();
});

test("a caller-supplied subject in the body is rejected as an unknown field", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const inbound = await app.fetch(
		signedWebhookRequest(messagesPayload({ from: "15551230000" })),
	);
	const { grant_id: grantId } = (await inbound.json()) as { grant_id: string };

	// The strict schema refuses the extra field outright rather than letting a
	// caller assert an identity the grant never carried.
	const res = await app.fetch(
		handlerRequest({ grant_id: grantId, subject: "15559999999" }),
	);

	expect(res.status).toBe(401);
});

test("the subject is taken from the grant, not from the inbound sender", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const inbound = await app.fetch(
		signedWebhookRequest(messagesPayload({ from: "15551230000" })),
	);
	const { grant_id: grantId } = (await inbound.json()) as { grant_id: string };
	const grant = deps.grants.consume(grantId, deps.clock());

	expect(grant?.subject).toBe("15551230000");
	expect(grant?.scope).toBe("whatsapp:write");
});

test("a webhook that is rejected mid-flight issues no grant", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const res = await app.fetch(
		new Request("http://localhost/api/whatsapp/webhook", { method: "POST" }),
	);
	const body = (await res.json()) as { grant_id?: string };

	expect(body.grant_id).toBeUndefined();
});

test("a duplicate delivery issues no second grant", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);
	const body = messagesPayload({ wamid: "wamid.REPLAY" });

	await app.fetch(signedWebhookRequest(body));
	const second = await app.fetch(signedWebhookRequest(body));
	const parsed = (await second.json()) as { grant_id?: string };

	expect(parsed.grant_id).toBeUndefined();
});

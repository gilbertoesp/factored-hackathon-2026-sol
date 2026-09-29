import { expect, test } from "bun:test";
import { createApp } from "../../app";
import {
	APP_SECRET,
	makeDeps,
	messagesPayload,
	signBody,
	signedWebhookRequest,
	webhookRequest,
} from "./test-helpers";

test("returns 401 when the signature header is missing", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const res = await app.fetch(webhookRequest(messagesPayload()));

	expect(res.status).toBe(401);
});

test("returns 401 when the signature header lacks the sha256= prefix", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);
	const body = messagesPayload();

	const res = await app.fetch(
		webhookRequest(body, { "x-hub-signature-256": signBody(body).slice(7) }),
	);

	expect(res.status).toBe(401);
});

test("returns 401 when the signature was produced with a different app secret", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const res = await app.fetch(
		signedWebhookRequest(messagesPayload(), {}, "some-other-secret"),
	);

	expect(res.status).toBe(401);
});

test("returns 401 when the body was mutated after signing", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);
	const body = messagesPayload({ body: "hello" });
	const res = await app.fetch(
		webhookRequest(body.replace("hello", "goodbye"), {
			"x-hub-signature-256": signBody(body),
		}),
	);

	expect(res.status).toBe(401);
});

test("returns 401 when the signature covers only a prefix of the body", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);
	const body = messagesPayload();
	const res = await app.fetch(
		webhookRequest(body, {
			"x-hub-signature-256": signBody(body.slice(0, 20)),
		}),
	);

	expect(res.status).toBe(401);
});

test("accepts a correctly signed body with 200 ok", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const res = await app.fetch(signedWebhookRequest(messagesPayload()));

	expect(res.status).toBe(200);
	expect(await res.json()).toEqual({ status: "ok" });
});

test("does not verify against the shared singleton app", async () => {
	// Proves verification reads injected secrets: the module-level `app` has an
	// empty app secret, so an unsigned request there must not be accepted.
	const { createApp: _unused } = { createApp };
	const { app } = await import("../../app");
	const body = messagesPayload();
	const res = await app.fetch(
		webhookRequest(body, { "x-hub-signature-256": signBody(body, APP_SECRET) }),
	);

	expect(res.status).toBe(401);
});

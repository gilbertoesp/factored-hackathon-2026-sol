import { expect, test } from "bun:test";
import { createApp } from "../../app";
import {
	makeDeps,
	messagesPayload,
	signBody,
	signedWebhookRequest,
	statusesPayload,
	webhookRequest,
} from "./test-helpers";

async function postSigned(
	deps: ReturnType<typeof makeDeps>["deps"],
	body: string,
) {
	return createApp(deps).fetch(signedWebhookRequest(body));
}

test("accepts a well-formed messages notification", async () => {
	const { deps } = makeDeps();
	const res = await postSigned(deps, messagesPayload());
	expect(res.status).toBe(200);
});

test("accepts a well-formed statuses notification", async () => {
	const { deps } = makeDeps();
	const res = await postSigned(deps, statusesPayload());
	expect(res.status).toBe(200);
});

test("rejects a payload whose object literal is not whatsapp_business_account", async () => {
	const { deps } = makeDeps();
	const body = messagesPayload().replace(
		"whatsapp_business_account",
		"instagram",
	);
	const res = await postSigned(deps, body);
	expect(res.status).toBe(400);
});

test("rejects a payload with an empty entry array", async () => {
	const { deps } = makeDeps();
	const body = JSON.stringify({
		object: "whatsapp_business_account",
		entry: [],
	});
	const res = await postSigned(deps, body);
	expect(res.status).toBe(400);
});

test("rejects a payload with an unknown changes field", async () => {
	const { deps } = makeDeps();
	const body = messagesPayload().replace('"messages"', '"message_echoes"');
	const res = await postSigned(deps, body);
	expect(res.status).toBe(400);
});

test("rejects malformed JSON with 400 rather than 500", async () => {
	const { deps } = makeDeps();
	const body = '{"object":"whatsapp_business_account",';
	const res = await postSigned(deps, body);
	expect(res.status).toBe(400);
});

test("rejects an unknown top-level key", async () => {
	const { deps } = makeDeps();
	const body = JSON.stringify({
		object: "whatsapp_business_account",
		entry: [],
		unexpected: true,
	});
	const res = await postSigned(deps, body);
	expect(res.status).toBe(400);
});

test("rejects a message missing its id", async () => {
	const { deps } = makeDeps();
	const body = messagesPayload().replace(/"id":"wamid\.AAA1",/, "");
	const res = await postSigned(deps, body);
	expect(res.status).toBe(400);
});

test("never echoes the request body back to the caller", async () => {
	const { deps } = makeDeps();
	const body = messagesPayload({ body: "my-secret-support-ticket" });
	const res = await postSigned(deps, body);
	const text = await res.text();
	expect(text).not.toContain("my-secret-support-ticket");
	expect(text).not.toContain("15551234567");
});

test("reports issue paths without the body", async () => {
	const { deps } = makeDeps();
	const body = messagesPayload().replace("whatsapp_business_account", "nope");
	const res = await postSigned(deps, body);
	const parsed = (await res.json()) as { issues: string[] };
	expect(Array.isArray(parsed.issues)).toBe(true);
	expect(parsed.issues.length).toBeGreaterThan(0);
});

test("validates the body even when the signature is valid", async () => {
	// Guards against an ordering mistake: a valid signature must not bypass the
	// schema, so signing an invalid body still yields 400 and never 200.
	const { deps } = makeDeps();
	const body = "not json at all";
	const res = await createApp(deps).fetch(
		webhookRequest(body, { "x-hub-signature-256": signBody(body) }),
	);
	expect(res.status).toBe(400);
});

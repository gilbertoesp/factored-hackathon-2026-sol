import { expect, test } from "bun:test";
import { createApp } from "../../app";
import {
	makeDeps,
	messagesPayload,
	signedWebhookRequest,
	webhookRequest,
} from "./test-helpers";

const url = "http://localhost";

// A correctly signed body is admitted, and hands back a grant for the Exit Seam.
test("Entry Seam: POST /api/whatsapp/webhook returns 200", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const res = await app.fetch(signedWebhookRequest(messagesPayload()));

	expect(res.status).toBe(200);
	const body = (await res.json()) as { status: string; grant_id?: string };
	expect(body.status).toBe("ok");
	expect(body.grant_id).toBeString();
});

// An unsigned body is now rejected at the Entry Seam rather than accepted.
test("Entry Seam: POST /api/whatsapp/webhook rejects an unsigned body", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const res = await app.fetch(webhookRequest(messagesPayload()));

	expect(res.status).toBe(401);
});

// The exported singleton stays wired at the documented path with no injected
// secrets, so an unverified request there is refused.
test("Entry Seam: the exported app mounts the webhook at the documented path", async () => {
	const { app } = await import("../../app");

	const res = await app.fetch(
		new Request(`${url}/api/whatsapp/webhook`, { method: "POST" }),
	);

	expect(res.status).toBe(401);
});

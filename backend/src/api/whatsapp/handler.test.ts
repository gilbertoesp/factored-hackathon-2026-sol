import { expect, test } from "bun:test";
import { createApp } from "../../app";
import {
	APP_SECRET,
	handlerRequest,
	makeDeps,
	messagesPayload,
	signedWebhookRequest,
	VERIFY_TOKEN,
} from "./test-helpers";

const url = "http://localhost";

// The Exit Seam is gated by a single-use grant issued at the Entry Seam. The
// full admit-then-consume path is covered in grants.test.ts; this file pins the
// documented route and the unauthenticated default.
test("Exit Seam: POST /api/whatsapp/handler without a grant returns 401", async () => {
	const { deps } = makeDeps();
	const res = await createApp(deps).fetch(
		new Request(`${url}/api/whatsapp/handler`, { method: "POST" }),
	);

	expect(res.status).toBe(401);
});

test("Exit Seam: an admitted grant returns 200 accepted", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const inbound = await app.fetch(
		signedWebhookRequest(messagesPayload({ from: "15551234567" })),
	);
	const { grant_id: grantId } = (await inbound.json()) as { grant_id: string };

	const res = await createApp(deps).fetch(handlerRequest(grantId));

	expect(res.status).toBe(200);
	expect(await res.json()).toEqual({ status: "accepted" });
});

test("Exit Seam: a grant issued to the default deps is accepted by the default deps", async () => {
	// The production path builds the app with secrets only, letting every other
	// dep default. If the two routers resolved their defaults independently they
	// would get separate grant stores, and no grant would ever survive the trip
	// from the Entry Seam to the Exit Seam.
	const app = createApp({
		secrets: { appSecret: APP_SECRET, verifyToken: VERIFY_TOKEN },
	});

	const inbound = await app.fetch(signedWebhookRequest(messagesPayload()));
	const { grant_id: grantId } = (await inbound.json()) as { grant_id: string };
	expect(grantId).toBeString();

	const res = await app.fetch(handlerRequest(grantId));

	expect(res.status).toBe(200);
	expect(await res.json()).toEqual({ status: "accepted" });
});

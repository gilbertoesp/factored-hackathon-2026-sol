import { expect, test } from "bun:test";
import { createApp } from "../../app";
import {
	makeDeps,
	messagesPayload,
	signedWebhookRequest,
	statusesPayload,
} from "./test-helpers";

async function post(
	deps: ReturnType<typeof makeDeps>["deps"],
	body: string,
): Promise<Response> {
	return createApp(deps).fetch(signedWebhookRequest(body));
}

test("first delivery of a message is accepted", async () => {
	const { deps } = makeDeps();
	const res = await post(deps, messagesPayload({ wamid: "wamid.ONE" }));
	expect(res.status).toBe(200);
	expect(await res.json()).toEqual({ status: "ok" });
});

test("a replayed message is acknowledged without reprocessing", async () => {
	const { deps } = makeDeps();
	const body = messagesPayload({ wamid: "wamid.ONE" });

	await post(deps, body);
	const res = await post(deps, body);

	expect(res.status).toBe(200);
	expect(await res.json()).toEqual({ status: "duplicate" });
});

test("a distinct message id is not treated as a replay", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	await app.fetch(
		signedWebhookRequest(messagesPayload({ wamid: "wamid.ONE" })),
	);
	const res = await app.fetch(
		signedWebhookRequest(messagesPayload({ wamid: "wamid.TWO" })),
	);

	expect(await res.json()).toEqual({ status: "ok" });
});

test("the same message id under a different WABA is a distinct delivery", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	await app.fetch(
		signedWebhookRequest(
			messagesPayload({ wamid: "wamid.SAME", entryId: "WABA_1" }),
		),
	);
	const res = await app.fetch(
		signedWebhookRequest(
			messagesPayload({ wamid: "wamid.SAME", entryId: "WABA_2" }),
		),
	);

	expect(await res.json()).toEqual({ status: "ok" });
});

test("replayed status updates are deduplicated by their status id", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);
	const body = statusesPayload({ statusId: "wamid.STATUS1" });

	await app.fetch(signedWebhookRequest(body));
	const res = await app.fetch(signedWebhookRequest(body));

	expect(await res.json()).toEqual({ status: "duplicate" });
});

test("a message id and a status id do not collide", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	await app.fetch(
		signedWebhookRequest(messagesPayload({ wamid: "wamid.COLLIDE" })),
	);
	const res = await app.fetch(
		signedWebhookRequest(statusesPayload({ statusId: "wamid.COLLIDE" })),
	);

	expect(await res.json()).toEqual({ status: "ok" });
});

test("a message is re-admitted once its entry has aged out of the dedup window", async () => {
	const { deps, advance } = makeDeps();
	const app = createApp(deps);
	const body = messagesPayload({ wamid: "wamid.OLD" });

	await app.fetch(signedWebhookRequest(body));
	advance(25 * 60 * 60 * 1000);
	const res = await app.fetch(signedWebhookRequest(body));

	expect(await res.json()).toEqual({ status: "ok" });
});

test("a replay within the window is still refused after the window was checked", async () => {
	// Guards the eviction loop: checking for expiry must not admit a replay that
	// is still inside the window.
	const { deps, advance } = makeDeps();
	const app = createApp(deps);
	const body = messagesPayload({ wamid: "wamid.NEAR" });

	await app.fetch(signedWebhookRequest(body));
	advance(23 * 60 * 60 * 1000);
	const res = await app.fetch(signedWebhookRequest(body));

	expect(await res.json()).toEqual({ status: "duplicate" });
});

test("dedup state does not leak between two apps built from separate deps", async () => {
	const first = makeDeps();
	const second = makeDeps();
	const body = messagesPayload({ wamid: "wamid.ISOLATED" });

	await createApp(first.deps).fetch(signedWebhookRequest(body));
	const res = await createApp(second.deps).fetch(signedWebhookRequest(body));

	expect(await res.json()).toEqual({ status: "ok" });
});

import { expect, test } from "bun:test";
import { createApp } from "../../app";
import {
	createDelegationKeys,
	mintDelegationToken,
	verifyDelegationToken,
} from "./delegation";
import { defaultWebhookDeps, RecordingTelemetry } from "./deps";
import {
	makeDeps,
	messagesPayload,
	signedWebhookRequest,
	webhookRequest,
} from "./test-helpers";

const keys = await createDelegationKeys();

test("an admitted message yields a grant carrying a delegation token", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const inbound = await app.fetch(
		signedWebhookRequest(messagesPayload({ from: "15551234567" })),
	);
	const { grant_id: grantId } = (await inbound.json()) as { grant_id: string };
	const grant = deps.grants.consume(grantId, deps.clock());
	const ring = await deps.keyRing.ready();

	expect(grant?.token).toBeString();
	const result = await verifyDelegationToken(
		grant?.token ?? "",
		ring.publicJwk,
		{
			expectedActor: "agent",
			requiredScope: "whatsapp:write",
		},
	);
	expect(result.ok).toBe(true);
});

test("the granted token is signed by the key ring the Exit Seam verifies with", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const inbound = await app.fetch(
		signedWebhookRequest(messagesPayload({ from: "15551234567" })),
	);
	const { grant_id: grantId } = (await inbound.json()) as { grant_id: string };
	const grant = deps.grants.consume(grantId, deps.clock());
	const ring = await deps.keyRing.ready();

	const result = await verifyDelegationToken(
		grant?.token ?? "",
		ring.publicJwk,
		{
			expectedActor: "agent",
		},
	);
	expect(result.ok).toBe(true);
});

test("a token minted for the sender names that sender as subject", async () => {
	const token = await mintDelegationToken({
		subject: "15551234567",
		actor: "agent",
		requestedScope: "whatsapp:write",
		keys,
	});
	const { payload } = await verifyDelegationToken(token, keys.publicJwk);

	expect(payload?.sub).toBe("15551234567");
});

test("a statuses-only notification issues no grant and no token", async () => {
	const { deps } = makeDeps();
	const { statusesPayload } = await import("./test-helpers");

	const res = await createApp(deps).fetch(
		signedWebhookRequest(statusesPayload({ statusId: "wamid.S1" })),
	);
	const body = (await res.json()) as { grant_id?: string };

	expect(body.grant_id).toBeUndefined();
});

test("an unsigned request never reaches the grant or token path", async () => {
	let issued = 0;
	const { deps } = makeDeps();
	const original = deps.grants.issue.bind(deps.grants);
	deps.grants = {
		...deps.grants,
		issue: (subject, scope, now) => {
			issued += 1;
			return original(subject, scope, now);
		},
	};

	await createApp(deps).fetch(webhookRequest(messagesPayload()));

	expect(issued).toBe(0);
});

test("the delegation key set is a distinct key pair per service instance", async () => {
	const other = await createDelegationKeys();
	expect(other.publicJwk.kid ?? JSON.stringify(other.publicJwk)).not.toBe(
		keys.publicJwk.kid ?? JSON.stringify(keys.publicJwk),
	);
});

test("an unknown token string is refused at verification", async () => {
	const result = await verifyDelegationToken("not-a-jwt", keys.publicJwk);
	expect(result.ok).toBe(false);
});

test("a grant carrying no token is refused at the Exit Seam", async () => {
	// The Cloud API dispatch is planned, so the Exit Seam stops at grant and
	// token validation. An empty token must not pass as a valid delegation.
	const { deps } = makeDeps();
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

	const res = await app.fetch(
		new Request("http://localhost/api/whatsapp/handler", {
			method: "POST",
			headers: { "content-type": "application/json" },
			body: JSON.stringify({ grant_id: grantId }),
		}),
	);

	// The token is what carries authority, so an empty one is refused as
	// forbidden rather than treated as an absent grant.
	expect(res.status).toBe(403);
});

test("default deps expose a recording telemetry port", () => {
	const deps = defaultWebhookDeps();
	expect(deps.telemetry).toBeInstanceOf(RecordingTelemetry);
});

import { expect, test } from "bun:test";
import { createApp } from "../../app";
import { createDelegationKeys, verifyDelegationToken } from "./delegation";
import {
	handlerRequest,
	makeDeps,
	messagesPayload,
	signedWebhookRequest,
	statusesPayload,
	verifiedPayload,
	webhookRequest,
} from "./test-helpers";

async function admit(deps: ReturnType<typeof makeDeps>["deps"]) {
	const res = await createApp(deps).fetch(
		signedWebhookRequest(messagesPayload({ from: "15551234567" })),
	);
	const body = (await res.json()) as { grant_id?: string };
	if (body.grant_id === undefined)
		throw new Error("expected a grant to be issued");
	return body.grant_id;
}

test("an admitted message yields a grant carrying a delegation token", async () => {
	const { deps } = makeDeps();
	const grantId = await admit(deps);

	const grant = deps.grants.consume(grantId, deps.clock());
	expect(grant?.token).toBeString();
});

test("the granted token is signed by the key ring the Exit Seam verifies with", async () => {
	const { deps } = makeDeps();
	const grantId = await admit(deps);
	const grant = deps.grants.consume(grantId, deps.clock());
	const { publicJwk } = await deps.keyRing.ready();

	const payload = verifiedPayload(
		await verifyDelegationToken(grant?.token ?? "", publicJwk, {
			expectedActor: "agent",
			requiredScope: "whatsapp:write",
		}),
	);

	expect(payload.sub).toBe("15551234567");
});

test("the granted token is refused when verified against another key ring", async () => {
	const { deps } = makeDeps();
	const grantId = await admit(deps);
	const grant = deps.grants.consume(grantId, deps.clock());
	const other = await createDelegationKeys();

	const result = await verifyDelegationToken(
		grant?.token ?? "",
		other.publicJwk,
	);

	expect(result.ok).toBe(false);
});

test("each test's key ring holds distinct key material", async () => {
	const first = await makeDeps().deps.keyRing.ready();
	const second = await makeDeps().deps.keyRing.ready();

	expect(first.publicJwk.x).not.toBe(second.publicJwk.x);
});

test("a statuses-only notification issues no grant and no token", async () => {
	const { deps } = makeDeps();

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

test("an unknown token string is refused at verification", async () => {
	const { deps } = makeDeps();
	const { publicJwk } = await deps.keyRing.ready();

	const result = await verifyDelegationToken("not-a-jwt", publicJwk);

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

	const res = await createApp(deps).fetch(handlerRequest(await admit(deps)));

	// The token is what carries authority, so an empty one is refused as
	// forbidden rather than treated as an absent grant.
	expect(res.status).toBe(403);
});

test("a grant minted for one sender cannot act on another", async () => {
	const { deps } = makeDeps();
	const grantId = await admit(deps);
	const grant = deps.grants.consume(grantId, deps.clock());
	const { publicJwk } = await deps.keyRing.ready();
	const payload = verifiedPayload(
		await verifyDelegationToken(grant?.token ?? "", publicJwk),
	);

	expect(payload.sub).toBe("15551234567");
	expect(payload.may_act).toEqual({ sub: "agent" });
});

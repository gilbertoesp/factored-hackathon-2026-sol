import { expect, test } from "bun:test";
import { generateKeyPair, type JWK, type KeyLike, SignJWT } from "jose";
import {
	ALLOWED_SCOPES,
	capScope,
	createDelegationKeys,
	DELEGATION_ALG,
	DELEGATION_AUDIENCE,
	DELEGATION_ISSUER,
	mintDelegationToken,
	verifyDelegationToken,
} from "./delegation";

const keys = await createDelegationKeys();

function signer(overrides: { kid?: string; alg?: string } = {}) {
	return async (
		claims: Record<string, unknown>,
		protectedHeader: Record<string, unknown> = {},
		expiresIn = "60s",
	) => {
		let key = keys.privateKey;
		if (overrides.alg && overrides.alg !== DELEGATION_ALG) {
			const pair = await generateKeyPair(overrides.alg as "HS256", {
				extractable: true,
			});
			key = pair.privateKey as KeyLike;
		}
		return new SignJWT(claims)
			.setProtectedHeader({
				alg: overrides.alg ?? DELEGATION_ALG,
				...protectedHeader,
			})
			.setIssuer(String(claims.iss ?? DELEGATION_ISSUER))
			.setAudience(String(claims.aud ?? DELEGATION_AUDIENCE))
			.setSubject(String(claims.sub ?? "15551234567"))
			.setIssuedAt()
			.setExpirationTime(expiresIn)
			.setJti(String(claims.jti ?? "jti-1"))
			.sign(key);
	};
}

const sign = signer();

test("a freshly minted token verifies", async () => {
	const token = await mintDelegationToken({
		subject: "15551234567",
		actor: "agent",
		requestedScope: "whatsapp:write",
		keys,
	});

	const result = await verifyDelegationToken(token, keys.publicJwk);

	expect(result.ok).toBe(true);
});

test("the token carries the sender as subject and the agent as actor", async () => {
	const token = await mintDelegationToken({
		subject: "15551234567",
		actor: "agent",
		requestedScope: "whatsapp:write",
		keys,
	});

	const { payload } = await verifyDelegationToken(token, keys.publicJwk);

	expect(payload?.sub).toBe("15551234567");
	expect(payload?.act).toEqual({ sub: "agent" });
});

test("may_act names who is permitted to act on the subject", async () => {
	const token = await mintDelegationToken({
		subject: "15551234567",
		actor: "agent",
		requestedScope: "whatsapp:write",
		keys,
	});

	const { payload } = await verifyDelegationToken(token, keys.publicJwk);

	expect(payload?.may_act).toEqual({ sub: "agent" });
});

test("issuer and audience are pinned to the delegation service", async () => {
	const token = await mintDelegationToken({
		subject: "15551234567",
		actor: "agent",
		requestedScope: "whatsapp:write",
		keys,
	});

	const { payload } = await verifyDelegationToken(token, keys.publicJwk);

	expect(payload?.iss).toBe(DELEGATION_ISSUER);
	expect(payload?.aud).toBe(DELEGATION_AUDIENCE);
});

test("the token expires within a minute of issue", async () => {
	const issuedAt = 1_700_000_000;
	const token = await mintDelegationToken({
		subject: "15551234567",
		actor: "agent",
		requestedScope: "whatsapp:write",
		keys,
		now: () => issuedAt,
	});

	const { payload } = await verifyDelegationToken(token, keys.publicJwk, {
		now: () => issuedAt * 1000,
	});

	expect(payload?.exp).toBe((payload?.iat ?? 0) + 60);
});

test("a token with a unique jti is issued per call", async () => {
	const first = await mintDelegationToken({
		subject: "15551234567",
		actor: "agent",
		requestedScope: "whatsapp:write",
		keys,
	});
	const second = await mintDelegationToken({
		subject: "15551234567",
		actor: "agent",
		requestedScope: "whatsapp:write",
		keys,
	});

	const a = await verifyDelegationToken(first, keys.publicJwk);
	const b = await verifyDelegationToken(second, keys.publicJwk);

	expect(a.payload?.jti).not.toBe(b.payload?.jti);
});

test("an expired token is rejected", async () => {
	// minted at a fixed epoch (seconds) so expiry is deterministic
	const issuedAtSeconds = 1_700_000_000;
	const token = await mintDelegationToken({
		subject: "15551234567",
		actor: "agent",
		requestedScope: "whatsapp:write",
		keys,
		now: () => issuedAtSeconds,
	});

	const result = await verifyDelegationToken(token, keys.publicJwk, {
		now: () => issuedAtSeconds * 1000 + 61_000,
	});

	expect(result.ok).toBe(false);
	expect(result.ok === false && result.reason).toContain("exp");
});

test("a token issued for another audience is rejected", async () => {
	const token = await sign({
		iss: DELEGATION_ISSUER,
		aud: "https://elsewhere",
	});

	const result = await verifyDelegationToken(token, keys.publicJwk);

	expect(result.ok).toBe(false);
});

test("a token issued by another issuer is rejected", async () => {
	const token = await sign({
		iss: "https://evil.example",
		aud: DELEGATION_AUDIENCE,
	});

	const result = await verifyDelegationToken(token, keys.publicJwk);

	expect(result.ok).toBe(false);
});

test("a tampered payload is rejected", async () => {
	const token = await mintDelegationToken({
		subject: "15551234567",
		actor: "agent",
		requestedScope: "whatsapp:write",
		keys,
	});

	const [header, payload, signature] = token.split(".");
	const claims = JSON.parse(
		Buffer.from(payload ?? "", "base64url").toString("utf8"),
	) as Record<string, unknown>;
	// Escalate the subject while keeping a structurally valid token.
	claims.sub = "15559999999";
	const forged = Buffer.from(JSON.stringify(claims)).toString("base64url");

	const result = await verifyDelegationToken(
		`${header}.${forged}.${signature}`,
		keys.publicJwk,
	);

	expect(result.ok).toBe(false);
});

test("a token signed with a different key is rejected", async () => {
	const other = await createDelegationKeys();
	const token = await mintDelegationToken({
		subject: "15551234567",
		actor: "agent",
		requestedScope: "whatsapp:write",
		keys: other,
		now: () => 1_700_000_000,
	});

	const result = await verifyDelegationToken(token, keys.publicJwk);

	expect(result.ok).toBe(false);
});

test("a symmetrically signed token is rejected", async () => {
	// Guards against alg confusion: HS256 with the public key as the secret
	// would otherwise let anyone mint a token the verifier accepts.
	const token = await sign(
		{ iss: DELEGATION_ISSUER, aud: DELEGATION_AUDIENCE },
		{},
		"60s",
	);
	const result = await verifyDelegationToken(token, keys.publicJwk);

	expect(result.ok).toBe(false);
});

test("scope is capped to the allowlist rather than passed through", () => {
	expect(capScope("whatsapp:admin whatsapp:write")).toBe("whatsapp:write");
});

test("a read-only request is not elevated to write", () => {
	expect(capScope("whatsapp:read")).toBe("whatsapp:read");
});

test("a scope outside the allowlist yields an empty scope", () => {
	expect(capScope("whatsapp:admin")).toBe("");
});

test("the allowlist contains only the two documented scopes", () => {
	expect([...ALLOWED_SCOPES].sort()).toEqual([
		"whatsapp:read",
		"whatsapp:write",
	]);
});

test("minting drops a requested scope outside the allowlist", async () => {
	const token = await mintDelegationToken({
		subject: "15551234567",
		actor: "agent",
		requestedScope: "whatsapp:admin whatsapp:write",
		keys,
	});

	const { payload } = await verifyDelegationToken(token, keys.publicJwk);

	expect(payload?.scope).toBe("whatsapp:write");
});

test("a token with no scope claim is rejected as unusable for writes", async () => {
	const token = await sign({
		iss: DELEGATION_ISSUER,
		aud: DELEGATION_AUDIENCE,
	});

	const result = await verifyDelegationToken(token, keys.publicJwk, {
		requiredScope: "whatsapp:write",
	});

	expect(result.ok).toBe(false);
});

test("a token whose act claim is missing is rejected", async () => {
	const token = await sign({
		iss: DELEGATION_ISSUER,
		aud: DELEGATION_AUDIENCE,
		scope: "whatsapp:write",
		may_act: { sub: "agent" },
	});

	const result = await verifyDelegationToken(token, keys.publicJwk);

	expect(result.ok).toBe(false);
});

test("a token whose act claim names a different actor is rejected", async () => {
	const token = await sign({
		iss: DELEGATION_ISSUER,
		aud: DELEGATION_AUDIENCE,
		scope: "whatsapp:write",
		act: { sub: "someone-else" },
		may_act: { sub: "agent" },
	});

	const result = await verifyDelegationToken(token, keys.publicJwk, {
		expectedActor: "agent",
	});

	expect(result.ok).toBe(false);
});

test("a token whose may_act omits the agent is rejected", async () => {
	const token = await sign({
		iss: DELEGATION_ISSUER,
		aud: DELEGATION_AUDIENCE,
		scope: "whatsapp:write",
		act: { sub: "agent" },
		may_act: { sub: "someone-else" },
	});

	const result = await verifyDelegationToken(token, keys.publicJwk, {
		expectedActor: "agent",
	});

	expect(result.ok).toBe(false);
});

test("a nested act chain resolves to the outermost actor", async () => {
	const token = await sign({
		iss: DELEGATION_ISSUER,
		aud: DELEGATION_AUDIENCE,
		scope: "whatsapp:write",
		// Outermost act is the current actor; nesting is the history trail.
		act: { sub: "agent", act: { sub: "gateway" } },
		may_act: { sub: "agent" },
	});

	const result = await verifyDelegationToken(token, keys.publicJwk, {
		expectedActor: "agent",
	});

	expect(result.ok).toBe(true);
});

test("a token with no may_act claim is rejected", async () => {
	const token = await sign({
		iss: DELEGATION_ISSUER,
		aud: DELEGATION_AUDIENCE,
		scope: "whatsapp:write",
		act: { sub: "agent" },
	});

	const result = await verifyDelegationToken(token, keys.publicJwk, {
		expectedActor: "agent",
	});

	expect(result.ok).toBe(false);
});

test("a read-only token is refused when write access is required", async () => {
	const token = await mintDelegationToken({
		subject: "15551234567",
		actor: "agent",
		requestedScope: "whatsapp:read",
		keys,
	});

	const result = await verifyDelegationToken(token, keys.publicJwk, {
		requiredScope: "whatsapp:write",
	});

	expect(result.ok).toBe(false);
});

test("the public key is a JWK carrying the expected algorithm", async () => {
	const jwk = keys.publicJwk as JWK;
	expect(jwk.alg).toBe(DELEGATION_ALG);
	expect(jwk.kty).toBe("EC");
});

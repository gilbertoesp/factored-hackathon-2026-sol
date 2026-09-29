import type { JWK, KeyLike } from "jose";
import {
	createLocalJWKSet,
	exportJWK,
	generateKeyPair,
	jwtVerify,
	SignJWT,
} from "jose";

export const DELEGATION_ALG = "ES256";
export const DELEGATION_ISSUER = "urn:factored:whatsapp:delegation";
export const DELEGATION_AUDIENCE = "urn:factored:whatsapp:cloud-api";
export const DELEGATION_TTL_SECONDS = 60;

/** The only scopes this service will ever mint. Anything else is dropped. */
export const ALLOWED_SCOPES = ["whatsapp:read", "whatsapp:write"] as const;

export interface DelegationKeys {
	privateKey: KeyLike;
	publicKey: KeyLike;
	publicJwk: JWK;
}

export interface MintInput {
	subject: string;
	actor: string;
	requestedScope: string;
	keys: DelegationKeys;
	now?: () => number;
}

export interface VerifyOptions {
	expectedActor?: string;
	requiredScope?: string;
	now?: () => number;
}

export type VerifyResult =
	| { ok: true; payload: Record<string, unknown> }
	| { ok: false; reason: string };

export async function createDelegationKeys(): Promise<DelegationKeys> {
	const { publicKey, privateKey } = await generateKeyPair(DELEGATION_ALG, {
		extractable: true,
	});
	const publicJwk = await exportJWK(publicKey);
	return {
		privateKey,
		publicKey,
		publicJwk: { ...publicJwk, alg: DELEGATION_ALG, use: "sig" },
	};
}

/**
 * Intersects a requested scope with the allowlist. This is an intersection, never
 * a union and never the request verbatim: an unrecognized scope is dropped
 * rather than erroring, so a broad request cannot widen the issued token.
 */
export function capScope(requested: string): string {
	const allowed = new Set<string>(ALLOWED_SCOPES);
	return requested
		.split(" ")
		.filter((scope) => scope.length > 0 && allowed.has(scope))
		.join(" ");
}

/**
 * Mints an RFC 8693 delegation token. `sub` is the WhatsApp sender, the outer
 * `act` is the agent acting for it, and `may_act` states who was permitted to
 * do so. Prior actors in a nested `act` are history only and are not consulted
 * for access control (RFC 8693 section 4.1).
 */
export async function mintDelegationToken(input: MintInput): Promise<string> {
	const now = input.now ?? (() => Math.floor(Date.now() / 1000));
	const issuedAt = now();

	return new SignJWT({
		act: { sub: input.actor },
		may_act: { sub: input.actor },
		scope: capScope(input.requestedScope),
	})
		.setProtectedHeader({ alg: DELEGATION_ALG })
		.setIssuer(DELEGATION_ISSUER)
		.setAudience(DELEGATION_AUDIENCE)
		.setSubject(input.subject)
		.setIssuedAt(issuedAt)
		.setExpirationTime(issuedAt + DELEGATION_TTL_SECONDS)
		.setJti(crypto.randomUUID())
		.sign(input.keys.privateKey);
}

/** Reads the current actor, which per RFC 8693 is the outermost `act`. */
function currentActor(act: unknown): string | undefined {
	if (typeof act !== "object" || act === null) return undefined;
	const sub = (act as { sub?: unknown }).sub;
	return typeof sub === "string" ? sub : undefined;
}

function hasSubjectClaim(value: unknown): boolean {
	return (
		typeof value === "object" &&
		value !== null &&
		typeof (value as { sub?: unknown }).sub === "string"
	);
}

export async function verifyDelegationToken(
	token: string,
	publicJwk: JWK,
	options: VerifyOptions = {},
): Promise<VerifyResult> {
	let payload: Record<string, unknown>;
	try {
		const verified = await jwtVerify(
			token,
			createLocalJWKSet({ keys: [publicJwk] }),
			{
				issuer: DELEGATION_ISSUER,
				audience: DELEGATION_AUDIENCE,
				algorithms: [DELEGATION_ALG],
				requiredClaims: ["sub", "scope", "act", "may_act"],
				...(options.now ? { currentDate: new Date(options.now()) } : {}),
			},
		);
		payload = verified.payload as Record<string, unknown>;
	} catch (error) {
		return { ok: false, reason: (error as Error).message };
	}

	// Delegation semantics: the agent may act only if the subject authorized it
	// and the token names that agent as the current actor.
	if (!hasSubjectClaim(payload.may_act)) {
		return { ok: false, reason: "may_act claim missing" };
	}
	if (currentActor(payload.act) === undefined) {
		return { ok: false, reason: "act claim missing" };
	}
	if (
		options.expectedActor !== undefined &&
		(currentActor(payload.act) !== options.expectedActor ||
			(payload.may_act as { sub?: unknown }).sub !== options.expectedActor)
	) {
		return { ok: false, reason: "actor is not authorized" };
	}

	if (options.requiredScope !== undefined) {
		const scopes = String(payload.scope ?? "").split(" ");
		if (!scopes.includes(options.requiredScope)) {
			return { ok: false, reason: `missing scope ${options.requiredScope}` };
		}
	}

	return { ok: true, payload };
}

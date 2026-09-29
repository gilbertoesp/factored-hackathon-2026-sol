import { createHmac, timingSafeEqual } from "node:crypto";

const SIGNATURE_HEADER = "x-hub-signature-256";
const PREFIX = "sha256=";

/**
 * Verifies Meta's X-Hub-Signature-256 over the raw body.
 *
 * The signature covers the exact bytes Meta sent, so the body must be read as
 * text and never re-serialized before hashing. Returns false rather than
 * throwing on any malformed input.
 */
export function verifySignature(
	rawBody: string,
	headerValue: string | undefined,
	appSecret: string,
): boolean {
	if (typeof headerValue !== "string") return false;
	if (!headerValue.startsWith(PREFIX)) return false;

	const provided = headerValue.slice(PREFIX.length);
	if (provided.length === 0 || !/^[0-9a-f]+$/i.test(provided)) return false;

	const expected = createHmac("sha256", appSecret)
		.update(rawBody, "utf8")
		.digest("hex");

	// timingSafeEqual throws on length mismatch, so compare buffers only after
	// confirming both sides are the same length.
	const a = Buffer.from(provided, "utf8");
	const b = Buffer.from(expected, "utf8");
	if (a.length !== b.length) return false;

	return timingSafeEqual(a, b);
}

export { SIGNATURE_HEADER };

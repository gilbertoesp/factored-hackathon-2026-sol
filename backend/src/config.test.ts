import { expect, test } from "bun:test";
import { loadConfig } from "./config";

/** A complete, valid environment, with overrides applied on top. */
function env(overrides: Record<string, string | undefined> = {}) {
	return {
		PORT: "4000",
		WHATSAPP_APP_SECRET: "app-secret",
		WHATSAPP_VERIFY_TOKEN: "verify-token",
		...overrides,
	} as Record<string, string | undefined>;
}

test("a complete environment loads", () => {
	const config = loadConfig(env());

	expect(config.port).toBe(4000);
	expect(config.whatsapp.appSecret).toBe("app-secret");
	expect(config.whatsapp.verifyToken).toBe("verify-token");
});

test("a missing app secret is rejected at boot", () => {
	// The alternative is a silent empty string, which rejects every webhook
	// with a 401 and looks like a Meta outage rather than a misconfiguration.
	expect(() => loadConfig(env({ WHATSAPP_APP_SECRET: undefined }))).toThrow(
		/WHATSAPP_APP_SECRET/,
	);
});

test("an empty app secret is rejected", () => {
	expect(() => loadConfig(env({ WHATSAPP_APP_SECRET: "" }))).toThrow(
		/WHATSAPP_APP_SECRET/,
	);
});

test("a missing verify token is rejected at boot", () => {
	expect(() => loadConfig(env({ WHATSAPP_VERIFY_TOKEN: undefined }))).toThrow(
		/WHATSAPP_VERIFY_TOKEN/,
	);
});

test("an empty verify token is rejected", () => {
	expect(() => loadConfig(env({ WHATSAPP_VERIFY_TOKEN: "" }))).toThrow(
		/WHATSAPP_VERIFY_TOKEN/,
	);
});

test("the port falls back to 4000 when unset", () => {
	expect(loadConfig(env({ PORT: undefined })).port).toBe(4000);
});

test("a non-numeric port is rejected", () => {
	expect(() => loadConfig(env({ PORT: "not-a-port" }))).toThrow(/PORT/);
});

test("a port outside the valid range is rejected", () => {
	expect(() => loadConfig(env({ PORT: "70000" }))).toThrow(/PORT/);
});

test("a port of zero is rejected", () => {
	// Port 0 means "pick an ephemeral port", which would silently move the
	// server off the port the platform routes traffic to.
	expect(() => loadConfig(env({ PORT: "0" }))).toThrow(/PORT/);
});

test("every missing variable is reported at once", () => {
	// Fixing one variable per boot cycle wastes a deploy on each typo.
	let message = "";
	try {
		loadConfig({} as Record<string, string | undefined>);
	} catch (error) {
		message = (error as Error).message;
	}

	expect(message).toContain("WHATSAPP_APP_SECRET");
	expect(message).toContain("WHATSAPP_VERIFY_TOKEN");
});

test("a rejected value is never echoed back", () => {
	let message = "";
	try {
		loadConfig(env({ WHATSAPP_APP_SECRET: "super-secret-leak" }));
	} catch (error) {
		message = (error as Error).message;
	}
	expect(message).not.toContain("super-secret-leak");
});

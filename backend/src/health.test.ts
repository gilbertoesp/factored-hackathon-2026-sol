import { expect, test } from "bun:test";
import { createApp } from "./app";

const url = "http://localhost";

test("a healthy app answers 200 on GET /health", async () => {
	const app = createApp();

	const res = await app.fetch(new Request(`${url}/health`));

	expect(res.status).toBe(200);
});

test("the healthy body is a fixed literal", async () => {
	// A health endpoint that echoes anything about itself is a leak waiting to
	// happen. The body is fixed so there is nothing to disclose.
	const app = createApp();

	const res = await app.fetch(new Request(`${url}/health`));

	expect(await res.json()).toEqual({ status: "ok" });
});

test("an app with an invalid config answers 503", async () => {
	// This is the case a TCP port probe cannot see: the process is listening,
	// but boot validation failed, so every webhook would be refused. The
	// healthcheck must report that, or a broken deploy looks healthy.
	const app = createApp({ config: { valid: false, errors: ["PORT"] } });

	const res = await app.fetch(new Request(`${url}/health`));

	expect(res.status).toBe(503);
});

test("an unhealthy body names the failing variables, never their values", async () => {
	const app = createApp({
		config: { valid: false, errors: ["WHATSAPP_APP_SECRET"] },
	});

	const res = await app.fetch(new Request(`${url}/health`));

	expect(await res.json()).toEqual({
		status: "unavailable",
		errors: ["WHATSAPP_APP_SECRET"],
	});
});

test("health reports no version, uptime, or host detail", async () => {
	const app = createApp();

	const res = await app.fetch(new Request(`${url}/health`));
	const body = JSON.stringify(await res.json());

	expect(body).not.toContain("version");
	expect(body).not.toContain("uptime");
	expect(body).not.toContain("hostname");
});

test("GET /health is mounted outside the WhatsApp seams", async () => {
	// It is not a WhatsApp route and must not inherit their auth or shape.
	const app = createApp();

	const res = await app.fetch(new Request(`${url}/api/whatsapp/health`));

	expect(res.status).toBe(404);
});

test("health does not require a signature or a grant", async () => {
	// A container probe has no Meta signature. Requiring one would make the
	// healthcheck permanently fail and the container restart forever.
	const app = createApp();

	const res = await app.fetch(new Request(`${url}/health`));

	expect(res.status).toBe(200);
});

test("POST /health is not allowed", async () => {
	// Only the probe should reach this. Keeping it GET-only means a bug that
	// POSTs here is visible rather than silently accepted.
	const app = createApp();

	const res = await app.fetch(new Request(`${url}/health`, { method: "POST" }));

	expect(res.status).toBe(405);
});

test("health responds when the app has no valid config and no errors", async () => {
	// Defensive: an empty error list must not read as healthy, or a broken
	// validator silently reports the service as up.
	const app = createApp({ config: { valid: false, errors: [] } });

	const res = await app.fetch(new Request(`${url}/health`));

	expect(res.status).toBe(503);
});

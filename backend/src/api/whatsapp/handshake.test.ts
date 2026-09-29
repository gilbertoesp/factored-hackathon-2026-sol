import { expect, test } from "bun:test";
import { createApp } from "../../app";
import { makeDeps, VERIFY_TOKEN, verifyRequest } from "./test-helpers";

test("echoes the challenge when mode and verify token match", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const res = await app.fetch(
		verifyRequest({
			"hub.mode": "subscribe",
			"hub.challenge": "1158201444",
			"hub.verify_token": VERIFY_TOKEN,
		}),
	);

	expect(res.status).toBe(200);
	expect(await res.text()).toBe("1158201444");
});

test("responds with text/plain so Meta accepts the challenge", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const res = await app.fetch(
		verifyRequest({
			"hub.mode": "subscribe",
			"hub.challenge": "42",
			"hub.verify_token": VERIFY_TOKEN,
		}),
	);

	expect(res.headers.get("content-type")).toContain("text/plain");
});

test("returns 403 when the verify token does not match", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const res = await app.fetch(
		verifyRequest({
			"hub.mode": "subscribe",
			"hub.challenge": "1158201444",
			"hub.verify_token": "wrong-token",
		}),
	);

	expect(res.status).toBe(403);
});

test("does not echo the challenge when the verify token is wrong", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const res = await app.fetch(
		verifyRequest({
			"hub.mode": "subscribe",
			"hub.challenge": "1158201444",
			"hub.verify_token": "wrong-token",
		}),
	);

	expect(await res.text()).not.toContain("1158201444");
});

test("returns 403 when hub.mode is missing", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const res = await app.fetch(
		verifyRequest({
			"hub.challenge": "1158201444",
			"hub.verify_token": VERIFY_TOKEN,
		}),
	);

	expect(res.status).toBe(403);
});

test("returns 403 when hub.challenge is missing", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const res = await app.fetch(
		verifyRequest({
			"hub.mode": "subscribe",
			"hub.verify_token": VERIFY_TOKEN,
		}),
	);

	expect(res.status).toBe(403);
});

test("returns 400 when hub.mode is not subscribe", async () => {
	const { deps } = makeDeps();
	const app = createApp(deps);

	const res = await app.fetch(
		verifyRequest({
			"hub.mode": "unsubscribe",
			"hub.challenge": "1158201444",
			"hub.verify_token": VERIFY_TOKEN,
		}),
	);

	expect(res.status).toBe(400);
});

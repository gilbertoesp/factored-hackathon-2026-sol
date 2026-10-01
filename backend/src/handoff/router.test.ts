import { describe, expect, test } from "bun:test";
import { createApp } from "../app";
import { createMemoryHandoffStore } from "./store";
import { ticket } from "./test-helpers";

const TOKEN = "advisor-test-token";

// An options object, not a defaulted parameter: passing undefined to a
// defaulted parameter would silently restore the token.
async function setup(
	{ advisorToken }: { advisorToken?: string } = { advisorToken: TOKEN },
) {
	const store = createMemoryHandoffStore();
	await store.save(ticket({ caseId: "a", createdAt: "2026-10-01T10:00:00Z" }));
	await store.save(
		ticket({
			caseId: "b",
			createdAt: "2026-10-01T11:00:00Z",
			originRule: "R04",
			queue: "Asesor reclamos",
			priority: "normal",
		}),
	);
	return createApp({ handoff: { store, advisorToken } });
}

const get = (path: string, token?: string) =>
	new Request(`http://local${path}`, {
		headers: token ? { authorization: `Bearer ${token}` } : {},
	});

describe("advisor handoff API", () => {
	test("lists every ficha newest first", async () => {
		const app = await setup();
		const res = await app.fetch(get("/api/handoff", TOKEN));
		expect(res.status).toBe(200);
		const body = (await res.json()) as { tickets: { caseId: string }[] };
		expect(body.tickets.map((t) => t.caseId)).toEqual(["b", "a"]);
	});

	test("filters by queue", async () => {
		const app = await setup();
		const res = await app.fetch(
			get(
				`/api/handoff?queue=${encodeURIComponent("Analista de fraude")}`,
				TOKEN,
			),
		);
		const body = (await res.json()) as { tickets: { caseId: string }[] };
		expect(body.tickets.map((t) => t.caseId)).toEqual(["a"]);
	});

	test("returns one ficha by case id, 404 when unknown", async () => {
		const app = await setup();
		const ok = await app.fetch(get("/api/handoff/a", TOKEN));
		expect(ok.status).toBe(200);
		expect(
			((await ok.json()) as { ticket: { caseId: string } }).ticket.caseId,
		).toBe("a");
		const missing = await app.fetch(get("/api/handoff/zzz", TOKEN));
		expect(missing.status).toBe(404);
	});

	test("rejects a missing or wrong token", async () => {
		const app = await setup();
		expect((await app.fetch(get("/api/handoff"))).status).toBe(401);
		expect((await app.fetch(get("/api/handoff/a", "wrong"))).status).toBe(401);
	});

	test("is disabled when no advisor token is configured", async () => {
		const app = await setup({});
		expect((await app.fetch(get("/api/handoff", TOKEN))).status).toBe(503);
	});

	test("is disabled by default in createApp", async () => {
		const res = await createApp().fetch(get("/api/handoff", TOKEN));
		expect(res.status).toBe(503);
	});

	test("offers no write route", async () => {
		const app = await setup();
		const res = await app.fetch(
			new Request("http://local/api/handoff", {
				method: "POST",
				headers: { authorization: `Bearer ${TOKEN}` },
				body: "{}",
			}),
		);
		expect(res.status).toBe(404);
	});
});

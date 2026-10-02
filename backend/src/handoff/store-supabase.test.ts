import { describe, expect, test } from "bun:test";
import { createClient } from "@supabase/supabase-js";
import { createSupabaseHandoffStore } from "./store-supabase";
import { ticket } from "./test-helpers";

/**
 * A stand-in for PostgREST that implements only what the store sends: insert
 * with on_conflict + ignore-duplicates, and select filtered by eq and ordered
 * by created_at. It records every request so tests can pin the wire contract
 * (the Prefer header is what makes a retry a no-op instead of a 409).
 */
function fakePostgrest() {
	const rows = new Map<string, Record<string, unknown>>();
	const requests: { method: string; url: URL; prefer: string }[] = [];

	const fetch = async (
		input: string | URL | Request,
		init?: RequestInit,
	): Promise<Response> => {
		const url = new URL(input.toString());
		const method = init?.method ?? "GET";
		const headers = new Headers(init?.headers);
		const prefer = headers.get("prefer") ?? "";
		requests.push({ method, url, prefer });

		if (method === "POST") {
			const body = JSON.parse(String(init?.body));
			const incoming = (Array.isArray(body) ? body : [body]) as Record<
				string,
				unknown
			>[];
			const inserted = incoming.filter((row) => {
				const key = String(row.case_id);
				if (rows.has(key)) return false;
				rows.set(key, row);
				return true;
			});
			return json(inserted.map(pick(url)), 201);
		}

		let result = [...rows.values()];
		for (const [column, value] of url.searchParams) {
			if (value.startsWith("eq.")) {
				result = result.filter((r) => String(r[column]) === value.slice(3));
			}
		}
		if (url.searchParams.get("order") === "created_at.desc") {
			result.sort(
				(a, b) =>
					Date.parse(String(b.created_at)) - Date.parse(String(a.created_at)),
			);
		}
		const selected = result.map(pick(url));
		if ((headers.get("accept") ?? "").includes("vnd.pgrst.object")) {
			return selected.length === 1
				? json(selected[0], 200)
				: json({ code: "PGRST116", message: "no rows" }, 406);
		}
		return json(selected, 200);
	};

	const client = createClient("http://supabase.test", "service-role-key", {
		auth: { persistSession: false },
		global: { fetch: fetch as typeof globalThis.fetch },
	});
	return { client, rows, requests };
}

const pick = (url: URL) => (row: Record<string, unknown>) => {
	const columns = (url.searchParams.get("select") ?? "*").split(",");
	if (columns[0] === "*") return row;
	return Object.fromEntries(columns.map((c) => [c, row[c]]));
};

const json = (body: unknown, status: number) =>
	new Response(JSON.stringify(body), {
		status,
		headers: { "content-type": "application/json" },
	});

describe("supabase handoff store", () => {
	test("saving the same case twice keeps the first ficha", async () => {
		const { client } = fakePostgrest();
		const store = createSupabaseHandoffStore(client);
		const first = await store.save(ticket());
		const retry = await store.save(ticket({ summary: "otro resumen" }));
		expect(first.created).toBe(true);
		expect(retry.created).toBe(false);
		expect(retry.ticket.summary).toBe(ticket().summary);
	});

	test("a retry is sent as ignore-duplicates on case_id, not a plain insert", async () => {
		const { client, requests } = fakePostgrest();
		await createSupabaseHandoffStore(client).save(ticket());
		const insert = requests.find((r) => r.method === "POST");
		expect(insert?.url.pathname).toBe("/rest/v1/handoff_tickets");
		expect(insert?.url.searchParams.get("on_conflict")).toBe("case_id");
		expect(insert?.prefer).toContain("resolution=ignore-duplicates");
	});

	test("the row columns repeat the ficha, as the table's check requires", async () => {
		const { client, rows } = fakePostgrest();
		const t = ticket();
		await createSupabaseHandoffStore(client).save(t);
		const row = rows.get(t.caseId);
		expect(row).toMatchObject({
			case_id: t.caseId,
			origin_rule: t.originRule,
			queue: t.queue,
			priority: t.priority,
			language: t.language,
			customer_id: t.customer?.customerId,
			created_at: t.createdAt,
		});
		expect(row?.ticket).toEqual(t);
	});

	test("an unauthenticated R02 ficha stores a null customer", async () => {
		const { client, rows } = fakePostgrest();
		const t = ticket({
			caseId: "r02",
			customer: null,
			originRule: "R02",
			queue: "Canal seguro / sucursal",
			priority: "normal",
			transactions: [],
			actions: [],
		});
		await createSupabaseHandoffStore(client).save(t);
		expect(rows.get("r02")?.customer_id).toBeNull();
	});

	test("get returns the ficha, or null when unknown", async () => {
		const { client } = fakePostgrest();
		const store = createSupabaseHandoffStore(client);
		await store.save(ticket({ caseId: "a" }));
		expect((await store.get("a"))?.caseId).toBe("a");
		expect(await store.get("zzz")).toBeNull();
	});

	test("lists newest first, all queues or one", async () => {
		const { client } = fakePostgrest();
		const store = createSupabaseHandoffStore(client);
		await store.save(
			ticket({ caseId: "a", createdAt: "2026-10-01T10:00:00Z" }),
		);
		await store.save(
			ticket({ caseId: "b", createdAt: "2026-10-01T11:00:00Z" }),
		);
		await store.save(
			ticket({
				caseId: "c",
				createdAt: "2026-10-01T12:00:00Z",
				originRule: "R04",
				queue: "Asesor reclamos",
				priority: "normal",
			}),
		);
		expect((await store.list()).map((t) => t.caseId)).toEqual(["c", "b", "a"]);
		expect(
			(await store.listByQueue("Analista de fraude")).map((t) => t.caseId),
		).toEqual(["b", "a"]);
	});

	test("a database error surfaces instead of reading as an empty list", async () => {
		const client = createClient("http://supabase.test", "key", {
			auth: { persistSession: false },
			global: {
				fetch: (async () =>
					json(
						{ code: "42501", message: "permission denied" },
						403,
					)) as unknown as typeof globalThis.fetch,
			},
		});
		const store = createSupabaseHandoffStore(client);
		await expect(store.list()).rejects.toThrow(/42501/);
		await expect(store.save(ticket())).rejects.toThrow(/save failed/);
	});
});

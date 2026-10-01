import { describe, expect, test } from "bun:test";
import { decide, type Facts } from "../rules/engine";
import { createMemoryHandoffStore } from "./store";
import { ticket } from "./test-helpers";
import { parseTicket } from "./ticket";

describe("ficha de derivación (R28)", () => {
	test("a complete ficha is accepted", () => {
		expect(parseTicket(ticket()).ok).toBe(true);
	});

	test("a blank required field is rejected", () => {
		const r = parseTicket(ticket({ summary: "   " }));
		expect(r.ok).toBe(false);
		if (!r.ok) expect(r.issues[0]).toStartWith("summary");
	});

	test("a missing required field is rejected", () => {
		const { queue: _queue, ...rest } = ticket();
		expect(parseTicket(rest).ok).toBe(false);
	});

	test("unknown fields are rejected, so nothing extra leaks to the advisor", () => {
		expect(parseTicket({ ...ticket(), document_number: "123" }).ok).toBe(false);
	});

	test("only R02 may come without a verified customer", () => {
		expect(parseTicket(ticket({ customer: null })).ok).toBe(false);
		expect(
			parseTicket(
				ticket({
					customer: null,
					originRule: "R02",
					queue: "Canal seguro / sucursal",
					priority: "normal",
					transactions: [],
					actions: [],
				}),
			).ok,
		).toBe(true);
	});

	test("a derivation about a known charge must carry the transaction", () => {
		const r = parseTicket(ticket({ transactions: [] }));
		expect(r.ok).toBe(false);
	});

	test("R04 may derive before any transaction is identified", () => {
		const r = parseTicket(
			ticket({
				originRule: "R04",
				queue: "Asesor reclamos",
				priority: "normal",
				transactions: [],
				actions: [],
			}),
		);
		expect(r.ok).toBe(true);
	});

	test("R18 is always high priority", () => {
		expect(parseTicket(ticket({ priority: "normal" })).ok).toBe(false);
	});

	test("R25 must hand over the pending action", () => {
		const base = { originRule: "R25" as const, priority: "normal" as const };
		expect(parseTicket(ticket(base)).ok).toBe(false);
		const pending = ticket({
			...base,
			actions: [
				{
					tool: "tarjeta.bloquear",
					status: "pendiente",
					reference: null,
					at: "2026-10-01T15:04:00-05:00",
				},
			],
		});
		expect(parseTicket(pending).ok).toBe(true);
	});

	test("R26 carries the verification alert", () => {
		const base = { originRule: "R26" as const, priority: "normal" as const };
		expect(parseTicket(ticket(base)).ok).toBe(false);
		expect(parseTicket(ticket({ ...base, alert: "verificacion" })).ok).toBe(
			true,
		);
	});

	test("the engine's handoff fits the ficha it must produce", () => {
		const facts: Facts = {
			session: { valid: true, otpFailures: 0, expiredMidFlow: false },
			message: { injectionAttempt: false, asksForHuman: false },
			intent: {
				label: "cargo_no_reconocido",
				confidence: 0.94,
				clarificationsAsked: 0,
			},
			search: {
				referencesForeignTransaction: false,
				candidates: 1,
				selected: true,
				clarificationsAsked: 0,
			},
			transaction: {
				status: "Approved",
				ageDays: 2,
				fraudScore: 74,
				amountUsd: 98.6,
				kind: "compra",
				hasOpenDispute: false,
			},
			customer: {
				recognizesCharge: false,
				unrecognizedCharges: 1,
				cardLostOrStolen: false,
				autoReversalsInPeriod: 0,
			},
		};
		const d = decide(facts);
		expect(d.ruleId).toBe("R18");
		expect(
			parseTicket(
				ticket({
					originRule: "R18",
					queue: d.handoff?.queue ?? "",
					priority: d.handoff?.priority ?? "normal",
				}),
			).ok,
		).toBe(true);
	});
});

describe("handoff store", () => {
	test("saving the same case twice keeps the first ficha", async () => {
		const store = createMemoryHandoffStore();
		const first = await store.save(ticket());
		const retry = await store.save(ticket({ summary: "otro resumen" }));
		expect(first.created).toBe(true);
		expect(retry.created).toBe(false);
		expect(retry.ticket.summary).toBe(ticket().summary);
	});

	test("lists a queue newest first", async () => {
		const store = createMemoryHandoffStore();
		await store.save(
			ticket({ caseId: "a", createdAt: "2026-10-01T10:00:00Z" }),
		);
		await store.save(
			ticket({ caseId: "b", createdAt: "2026-10-01T11:00:00Z" }),
		);
		await store.save(
			ticket({
				caseId: "c",
				originRule: "R04",
				queue: "Asesor reclamos",
				priority: "normal",
			}),
		);
		const fraud = await store.listByQueue("Analista de fraude");
		expect(fraud.map((t) => t.caseId)).toEqual(["b", "a"]);
		expect(await store.get("missing")).toBeNull();
	});
});

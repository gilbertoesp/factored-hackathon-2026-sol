import { afterAll, describe, expect, test } from "bun:test";
import { type Decision, decide, type Facts } from "./engine";
import { policy, RULE_IDS, type RuleId, toolNames } from "./policy";

/**
 * One block per rule of docs/matriz_decision_es.xlsx. Each case starts from a
 * customer with a valid session who reports one approved, low-risk charge
 * they do not recognize, and changes only the facts the rule is about.
 */

type DeepPartial<T> = { [K in keyof T]?: Partial<T[K]> };

function facts(overrides: DeepPartial<Facts> = {}): Facts {
	const base: Facts = {
		session: { valid: true, otpFailures: 0, expiredMidFlow: false },
		message: { injectionAttempt: false, asksForHuman: false },
		intent: {
			label: "cargo_no_reconocido",
			confidence: 0.92,
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
			ageDays: 5,
			fraudScore: 12,
			amountUsd: 40,
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
	const out = { ...base } as Record<string, unknown>;
	for (const [key, value] of Object.entries(overrides)) {
		const current = out[key];
		out[key] =
			value === undefined
				? undefined
				: { ...(current as object | undefined), ...value };
	}
	return out as unknown as Facts;
}

const decided = new Set<RuleId>();

function expectRule(decision: Decision, ruleId: RuleId): Decision {
	expect(decision.ruleId).toBe(ruleId);
	decided.add(ruleId);
	return decision;
}

const tools = (d: Decision) => d.tools.map((t) => t.name);

describe("1 Autenticación", () => {
	test("R01: no session asks for OTP and reveals nothing", () => {
		const d = expectRule(decide(facts({ session: { valid: false } })), "R01");
		expect(tools(d)).toEqual(["auth.enviar_otp"]);
		expect(d.handoff).toBeNull();
	});

	test("R01: a customer id typed in the chat does not count as a session", () => {
		// The classifier saw an id, but the session is still not valid.
		const d = decide(
			facts({ session: { valid: false }, intent: { confidence: 0.99 } }),
		);
		expect(d.ruleId).toBe("R01");
	});

	test("R02: 3 failed OTPs block the session, not the card", () => {
		const d = expectRule(
			decide(facts({ session: { valid: false, otpFailures: 3 } })),
			"R02",
		);
		expect(tools(d)).toContain("auth.bloquear_sesion");
		expect(tools(d)).toContain("log.seguridad");
		expect(tools(d)).not.toContain("tarjeta.bloquear");
		expect(d.handoff?.queue).toBe("Canal seguro / sucursal");
	});

	test("R02 does not trigger below the threshold", () => {
		const d = decide(facts({ session: { valid: false, otpFailures: 2 } }));
		expect(d.ruleId).toBe("R01");
	});

	test("R27: a session that lapses mid-flow stops the pending action", () => {
		const d = expectRule(
			decide(
				facts({
					session: { valid: false, expiredMidFlow: true },
					action: { failedAfterRetry: false, verified: true },
				}),
			),
			"R27",
		);
		expect(tools(d)).toEqual(["auth.enviar_otp"]);
	});
});

describe("1 Seguridad", () => {
	test("R03: an injection attempt runs no action", () => {
		const d = expectRule(
			decide(
				facts({
					message: { injectionAttempt: true },
					transaction: { fraudScore: 95 },
				}),
			),
			"R03",
		);
		expect(tools(d)).toEqual(["log.seguridad"]);
	});

	test("R03 is checked after authentication", () => {
		const d = decide(
			facts({ session: { valid: false }, message: { injectionAttempt: true } }),
		);
		expect(d.ruleId).toBe("R01");
	});

	test("R04: asking for a person derives at once with a ficha", () => {
		const d = expectRule(
			decide(facts({ message: { asksForHuman: true } })),
			"R04",
		);
		expect(tools(d)).toEqual(["handoff.crear_ficha"]);
		expect(d.handoff?.queue).toBe("Asesor reclamos");
	});
});

describe("2 Entender", () => {
	test("R05: low confidence asks a targeted question", () => {
		const d = expectRule(decide(facts({ intent: { confidence: 0.5 } })), "R05");
		expect(d.tools).toEqual([]);
	});

	test("R05: confidence exactly at the threshold is enough", () => {
		const d = decide(
			facts({ intent: { confidence: policy.thresholds.minIntentConfidence } }),
		);
		expect(d.ruleId).not.toBe("R05");
	});

	test("R06: still ambiguous after the maximum clarifications derives", () => {
		const d = expectRule(
			decide(
				facts({
					intent: {
						label: "ambigua",
						clarificationsAsked: policy.thresholds.maxClarifications,
					},
				}),
			),
			"R06",
		);
		expect(d.handoff).not.toBeNull();
	});

	test("R07: a simple card block runs the IVR tool, no claim", () => {
		const d = expectRule(
			decide(
				facts({
					intent: {
						label: "fuera_de_alcance",
						outOfScopeTopic: "bloqueo_tarjeta",
					},
				}),
			),
			"R07",
		);
		expect(tools(d)).toEqual(["tarjeta.bloquear"]);
		expect(d.handoff).toBeNull();
	});

	test("R07: a balance question only points to the right channel", () => {
		const d = decide(
			facts({ intent: { label: "fuera_de_alcance", outOfScopeTopic: "otro" } }),
		);
		expect(d.ruleId).toBe("R07");
		expect(d.tools).toEqual([]);
	});

	test("R08: a non-transactional complaint opens a generic claim", () => {
		const d = expectRule(
			decide(facts({ intent: { label: "otro_reclamo" } })),
			"R08",
		);
		expect(tools(d)).toEqual(["reclamo.abrir", "handoff.crear_ficha"]);
		expect(d.handoff?.queue).toBe("Back office PQR");
	});
});

describe("3 Identificar transacción", () => {
	test("without search results the engine asks for txn.buscar", () => {
		const d = decide(facts({ search: undefined }));
		expect(d.kind).toBe("awaiting");
		expect(tools(d)).toEqual(["txn.buscar"]);
	});

	test("R09: a transaction of another customer is refused and logged", () => {
		const d = expectRule(
			decide(facts({ search: { referencesForeignTransaction: true } })),
			"R09",
		);
		expect(tools(d)).toEqual(["log.seguridad"]);
	});

	test("R10: no candidates asks for amount or date", () => {
		const d = expectRule(
			decide(facts({ search: { candidates: 0, selected: false } })),
			"R10",
		);
		expect(d.handoff).toBeNull();
	});

	test("R10: no candidates after the maximum clarifications derives", () => {
		const d = expectRule(
			decide(
				facts({
					search: {
						candidates: 0,
						selected: false,
						clarificationsAsked: policy.thresholds.maxClarifications,
					},
				}),
			),
			"R10",
		);
		expect(d.handoff?.queue).toBe("Asesor reclamos");
	});

	test("R11: several candidates are shown, never picked blindly", () => {
		const d = expectRule(
			decide(facts({ search: { candidates: 3, selected: false } })),
			"R11",
		);
		expect(d.tools).toEqual([]);
	});

	test("R11 no longer applies once the customer picks one", () => {
		const d = decide(facts({ search: { candidates: 3, selected: true } }));
		expect(d.ruleId).not.toBe("R11");
	});

	test("R12: a charge older than the window derives", () => {
		const d = expectRule(
			decide(
				facts({
					transaction: { ageDays: policy.thresholds.searchWindowDays + 1 },
				}),
			),
			"R12",
		);
		expect(d.handoff).not.toBeNull();
	});

	test("R12: a charge exactly at the window is still automatic", () => {
		const d = decide(
			facts({ transaction: { ageDays: policy.thresholds.searchWindowDays } }),
		);
		expect(d.ruleId).not.toBe("R12");
	});

	test("R13: an open claim is reported, never duplicated", () => {
		const d = expectRule(
			decide(facts({ transaction: { hasOpenDispute: true } })),
			"R13",
		);
		expect(tools(d)).toEqual(["reclamo.consultar"]);
	});

	test("R14: a declined charge has nothing to dispute", () => {
		const d = expectRule(
			decide(facts({ transaction: { status: "Declined", fraudScore: 80 } })),
			"R14",
		);
		expect(tools(d)).not.toContain("reclamo.abrir");
	});

	test("R15: a low-risk pending hold schedules a follow-up", () => {
		const d = expectRule(
			decide(facts({ transaction: { status: "Pending" } })),
			"R15",
		);
		expect(tools(d)).toEqual(["seguimiento.programar"]);
	});

	test("R15 gives way to R18 when the pending hold is high risk", () => {
		const d = decide(
			facts({ transaction: { status: "Pending", fraudScore: 31 } }),
		);
		expect(d.ruleId).toBe("R18");
	});

	test("R16: a reversed charge is already resolved", () => {
		const d = expectRule(
			decide(facts({ transaction: { status: "Reversed" } })),
			"R16",
		);
		expect(tools(d)).toEqual(["txn.detalle"]);
	});
});

describe("4 Decidir: cargo no reconocido", () => {
	test("before the customer answers, the engine shows the detail", () => {
		const d = decide(facts({ customer: { recognizesCharge: undefined } }));
		expect(d.kind).toBe("awaiting");
		expect(tools(d)).toEqual(["txn.detalle"]);
	});

	test("R17: recognized after seeing the detail closes without a claim", () => {
		const d = expectRule(
			decide(facts({ customer: { recognizesCharge: true } })),
			"R17",
		);
		expect(tools(d)).toEqual(["caso.cerrar"]);
	});

	test("R18: fraud_score above 30 blocks, opens a fraud claim, priority", () => {
		const d = expectRule(
			decide(facts({ transaction: { fraudScore: 31 } })),
			"R18",
		);
		expect(tools(d)).toEqual([
			"tarjeta.bloquear",
			"reclamo.abrir",
			"handoff.crear_ficha",
		]);
		expect(d.handoff).toMatchObject({
			queue: "Analista de fraude",
			priority: "alta",
		});
	});

	test("R18: a score of exactly 30 is not an automatic block", () => {
		const d = decide(facts({ transaction: { fraudScore: 30 } }));
		expect(d.ruleId).toBe("R20");
		expect(tools(d)).not.toContain("tarjeta.bloquear");
	});

	test("R19: two unrecognized charges with a low score open a fraud claim", () => {
		const d = expectRule(
			decide(facts({ customer: { unrecognizedCharges: 2 } })),
			"R19",
		);
		expect(tools(d)).toEqual(["reclamo.abrir", "handoff.crear_ficha"]);
		expect(d.tools[0]?.args).toEqual({ tipo: "fraude" });
	});

	test("R19: the card is blocked only when the customer accepts", () => {
		const d = decide(
			facts({ customer: { cardLostOrStolen: true, acceptsBlock: true } }),
		);
		expect(d.ruleId).toBe("R19");
		expect(tools(d)[0]).toBe("tarjeta.bloquear");
	});

	test("R20: one low-risk charge opens a dispute for the back office", () => {
		const d = expectRule(decide(facts()), "R20");
		expect(d.tools[0]).toEqual({
			name: "reclamo.abrir",
			args: { tipo: "disputa" },
		});
		expect(tools(d)).not.toContain("tarjeta.bloquear");
		expect(d.handoff?.queue).toBe("Back office disputas");
	});
});

describe("4 Decidir: cobro indebido", () => {
	const fee = { intent: { label: "cobro_indebido" as const } };

	test("R21: a small first fee is reversed automatically", () => {
		const d = expectRule(
			decide(
				facts({ ...fee, transaction: { kind: "comision", amountUsd: 10 } }),
			),
			"R21",
		);
		expect(tools(d)).toEqual(["comision.revertir"]);
		expect(d.handoff).toBeNull();
	});

	test("R21: a fee exactly at the limit is still reversed", () => {
		const d = decide(
			facts({
				...fee,
				transaction: {
					kind: "comision",
					amountUsd: policy.thresholds.autoReversalLimitUsd,
				},
			}),
		);
		expect(d.ruleId).toBe("R21");
	});

	test("R22: a fee over the limit opens a claim and derives", () => {
		const d = expectRule(
			decide(
				facts({ ...fee, transaction: { kind: "comision", amountUsd: 26 } }),
			),
			"R22",
		);
		expect(tools(d)).toEqual(["reclamo.abrir", "handoff.crear_ficha"]);
	});

	test("R22: a second reversal in the period goes to an advisor", () => {
		const d = decide(
			facts({
				...fee,
				transaction: { kind: "comision", amountUsd: 5 },
				customer: { autoReversalsInPeriod: 1 },
			}),
		);
		expect(d.ruleId).toBe("R22");
	});

	test("R23: a small duplicate is reversed", () => {
		const d = expectRule(
			decide(
				facts({
					...fee,
					transaction: { amountUsd: 20, duplicateGapMinutes: 3 },
				}),
			),
			"R23",
		);
		expect(tools(d)).toEqual(["comision.revertir"]);
	});

	test("R23: a large duplicate opens a claim and derives", () => {
		const d = expectRule(
			decide(
				facts({
					...fee,
					transaction: { amountUsd: 200, duplicateGapMinutes: 3 },
				}),
			),
			"R23",
		);
		expect(tools(d)).toEqual(["reclamo.abrir", "handoff.crear_ficha"]);
	});

	test("charges further apart than the window are not duplicates", () => {
		const d = decide(
			facts({
				...fee,
				transaction: {
					amountUsd: 20,
					duplicateGapMinutes: policy.thresholds.duplicateWindowMinutes + 1,
				},
			}),
		);
		expect(d.ruleId).not.toBe("R23");
	});

	test("R29: a wrongful charge on a purchase opens a dispute with the merchant", () => {
		const d = expectRule(decide(facts(fee)), "R29");
		expect(d.tools[0]).toEqual({
			name: "reclamo.abrir",
			args: { tipo: "cobro_indebido" },
		});
		expect(tools(d)).not.toContain("comision.revertir");
		expect(tools(d)).not.toContain("tarjeta.bloquear");
		expect(d.handoff?.queue).toBe("Back office disputas");
	});

	test("R29: a small purchase is still not reversed automatically", () => {
		const d = decide(facts({ ...fee, transaction: { amountUsd: 3 } }));
		expect(d.ruleId).toBe("R29");
		expect(tools(d)).not.toContain("comision.revertir");
	});
});

describe("5 Verificar", () => {
	test("R24: a verified action is confirmed", () => {
		const d = expectRule(
			decide(facts({ action: { failedAfterRetry: false, verified: true } })),
			"R24",
		);
		expect(d.handoff).toBeNull();
	});

	test("R25: a tool that fails its retry is not confirmed", () => {
		const d = expectRule(
			decide(facts({ action: { failedAfterRetry: true, verified: false } })),
			"R25",
		);
		expect(d.handoff?.pendingAction).toBe(true);
	});

	test("R26: a mismatched verification derives with an alert", () => {
		const d = expectRule(
			decide(facts({ action: { failedAfterRetry: false, verified: false } })),
			"R26",
		);
		expect(d.handoff).toMatchObject({
			queue: "Asesor + alerta técnica",
			alert: "verificacion",
		});
	});
});

describe("6 Escalar", () => {
	test("R28: every derivation carries a ficha", () => {
		const cases: Facts[] = [
			facts({ session: { valid: false, otpFailures: 3 } }),
			facts({ message: { asksForHuman: true } }),
			facts({ intent: { label: "ambigua", clarificationsAsked: 2 } }),
			facts({ intent: { label: "otro_reclamo" } }),
			facts({ transaction: { ageDays: 400 } }),
			facts({ transaction: { fraudScore: 90 } }),
			facts(),
			facts({ action: { failedAfterRetry: true, verified: false } }),
			facts({ action: { failedAfterRetry: false, verified: false } }),
		];
		for (const c of cases) {
			const d = decide(c);
			expect(d.handoff).not.toBeNull();
			expect(tools(d)).toContain("handoff.crear_ficha");
		}
		decided.add("R28");
	});
});

describe("policy export", () => {
	test("every tool the engine names is listed for that rule in the matrix", () => {
		const all: Facts[] = [
			facts({ session: { valid: false } }),
			facts({ session: { valid: false, otpFailures: 3 } }),
			facts({ session: { valid: false, expiredMidFlow: true } }),
			facts({ message: { injectionAttempt: true } }),
			facts({ message: { asksForHuman: true } }),
			facts({
				intent: {
					label: "fuera_de_alcance",
					outOfScopeTopic: "bloqueo_tarjeta",
				},
			}),
			facts({ intent: { label: "otro_reclamo" } }),
			facts({ search: { referencesForeignTransaction: true } }),
			facts({ transaction: { hasOpenDispute: true } }),
			facts({ transaction: { status: "Declined" } }),
			facts({ transaction: { status: "Pending" } }),
			facts({ transaction: { status: "Reversed" } }),
			facts({ customer: { recognizesCharge: true } }),
			facts({ transaction: { fraudScore: 31 } }),
			facts({ customer: { cardLostOrStolen: true, acceptsBlock: true } }),
			facts({ customer: { acceptsBlock: true } }),
			facts({
				intent: { label: "cobro_indebido" },
				transaction: { kind: "comision", amountUsd: 5 },
			}),
			facts({
				intent: { label: "cobro_indebido" },
				transaction: { kind: "comision", amountUsd: 50 },
			}),
			facts({
				intent: { label: "cobro_indebido" },
				transaction: { amountUsd: 5, duplicateGapMinutes: 1 },
			}),
			facts({
				intent: { label: "cobro_indebido" },
				transaction: { amountUsd: 500, duplicateGapMinutes: 1 },
			}),
			facts({ intent: { label: "cobro_indebido" } }),
		];
		for (const c of all) {
			const d = decide(c);
			if (d.ruleId === null) continue;
			const allowed = toolNames(policy.rules[d.ruleId]);
			allowed.add("handoff.crear_ficha"); // R28 applies to any derivation
			for (const name of tools(d)) {
				expect({ rule: d.ruleId, tool: name, ok: allowed.has(name) }).toEqual({
					rule: d.ruleId,
					tool: name,
					ok: true,
				});
			}
		}
	});

	test("thresholds match the Umbrales sheet the evidence is based on", () => {
		expect(policy.thresholds.fraudScoreAutoBlock).toBe(30);
		expect(policy.thresholds.searchWindowDays).toBe(120);
	});
});

afterAll(() => {
	// One test per rule: fail loudly if a rule in the matrix has no case.
	const missing = RULE_IDS.filter((id) => !decided.has(id));
	if (missing.length > 0) {
		throw new Error(`Rules without a test: ${missing.join(", ")}`);
	}
});

import { policy as defaultPolicy, type Policy, type RuleId } from "./policy";

/**
 * The rules engine for the disputes agent (R01 to R29).
 *
 * A pure function from verified facts to one decision. It never calls a tool
 * and never reads the conversation: the orchestrator gathers facts (session,
 * classifier output, txn.buscar results, tool outcomes), asks the engine what
 * to do, runs the tools it names, and asks again. That split is what lets the
 * permission and business logic live in code instead of in the prompt (R03):
 * nothing the LLM says can reach a tool except through a fact the code has
 * already checked.
 *
 * Rules are evaluated in stage order and the first match decides, as the
 * matrix says. Within the authentication stage the more specific rules (R02,
 * R27) are checked before the catch-all R01, because all three describe a
 * session that is not valid.
 */

export type Intent =
	| "cargo_no_reconocido"
	| "cobro_indebido"
	| "fuera_de_alcance"
	| "otro_reclamo"
	| "ambigua";

export type TransactionStatus =
	| "Approved"
	| "Declined"
	| "Pending"
	| "Reversed";

export interface Facts {
	session: {
		valid: boolean;
		otpFailures: number;
		/** The session lapsed after the case started (R27, not R01). */
		expiredMidFlow: boolean;
	};
	message: {
		injectionAttempt: boolean;
		asksForHuman: boolean;
	};
	intent: {
		label: Intent;
		confidence: number;
		clarificationsAsked: number;
		/** Only for fuera_de_alcance: a plain card block is resolved here (R07). */
		outOfScopeTopic?: "bloqueo_tarjeta" | "otro";
	};
	/** Result of txn.buscar, scoped to the session customer by the tool layer. */
	search?: {
		/** The customer named a transaction that is not theirs (R09). */
		referencesForeignTransaction: boolean;
		candidates: number;
		/** The customer picked one candidate, or there was exactly one. */
		selected: boolean;
		clarificationsAsked: number;
	};
	transaction?: {
		status: TransactionStatus;
		ageDays: number;
		fraudScore: number;
		amountUsd: number;
		kind: "compra" | "comision";
		hasOpenDispute: boolean;
		/** Minutes to an identical earlier charge, when one exists (R23). */
		duplicateGapMinutes?: number;
	};
	customer?: {
		/** Undefined until the customer has seen the detail and answered. */
		recognizesCharge?: boolean;
		unrecognizedCharges: number;
		cardLostOrStolen: boolean;
		/** Automatic reversals already granted in the first-occurrence period. */
		autoReversalsInPeriod: number;
		acceptsBlock?: boolean;
	};
	/** Outcome of the last action step, after the tool layer's retry (R24-R26). */
	action?: {
		failedAfterRetry: boolean;
		verified: boolean;
	};
}

export interface ToolCall {
	name: string;
	args?: Record<string, string>;
}

export type Priority = "normal" | "alta";

export interface Handoff {
	queue: string;
	priority: Priority;
	alert?: "verificacion";
	/** An action was attempted and not confirmed; the advisor must finish it. */
	pendingAction?: boolean;
}

/** A fact the engine needs before any rule can decide. */
export type Awaiting = "search" | "transaction" | "customer.recognizesCharge";

export type Decision =
	| {
			kind: "rule";
			ruleId: RuleId;
			tools: ToolCall[];
			/** Set on every derivation; R28 then guarantees a ficha. */
			handoff: Handoff | null;
			message: string;
			metricOutcome: string;
	  }
	| {
			kind: "awaiting";
			ruleId: null;
			awaiting: Awaiting;
			tools: ToolCall[];
			handoff: null;
			message: string | null;
	  };

const FICHA: ToolCall = { name: "handoff.crear_ficha" };

export function decide(facts: Facts, p: Policy = defaultPolicy): Decision {
	const t = p.thresholds;

	const rule = (
		ruleId: RuleId,
		tools: ToolCall[],
		handoff: Handoff | null = null,
	): Decision => {
		const r = p.rules[ruleId];
		// R28: every derivation produces a structured ficha, whatever rule
		// triggered it. Enforced here so no rule can forget it.
		const withFicha =
			handoff && !tools.some((tool) => tool.name === FICHA.name)
				? [...tools, FICHA]
				: tools;
		return {
			kind: "rule",
			ruleId,
			tools: withFicha,
			handoff,
			message: r.message,
			metricOutcome: r.metricOutcome,
		};
	};
	const queueOf = (ruleId: RuleId): string =>
		p.rules[ruleId].queue ?? "Asesor reclamos";
	const derive = (ruleId: RuleId, extra: Partial<Handoff> = {}): Handoff => ({
		queue: queueOf(ruleId),
		priority: "normal",
		...extra,
	});

	// ---------------------------------------------------- 1 Autenticación
	const { session } = facts;
	if (session.otpFailures >= t.otpMaxAttempts) {
		return rule(
			"R02",
			[{ name: "auth.bloquear_sesion" }, { name: "log.seguridad" }],
			derive("R02"),
		);
	}
	if (!session.valid && session.expiredMidFlow) {
		return rule("R27", [{ name: "auth.enviar_otp" }]);
	}
	if (!session.valid) {
		return rule("R01", [{ name: "auth.enviar_otp" }]);
	}

	// ---------------------------------------------------- 1 Seguridad
	if (facts.message.injectionAttempt) {
		return rule("R03", [{ name: "log.seguridad" }]);
	}
	if (facts.message.asksForHuman) {
		return rule("R04", [FICHA], derive("R04"));
	}

	// ---------------------------------------------------- 5 Verificar
	// Evaluated before stages 2-4: once an action ran, the only open question
	// is whether to confirm it.
	if (facts.action) {
		if (facts.action.failedAfterRetry) {
			return rule("R25", [FICHA], derive("R25", { pendingAction: true }));
		}
		if (!facts.action.verified) {
			return rule(
				"R26",
				[{ name: "handoff.crear_ficha", args: { alerta: "verificacion" } }],
				derive("R26", { alert: "verificacion" }),
			);
		}
		return rule("R24", []);
	}

	// ---------------------------------------------------- 2 Entender
	const { intent } = facts;
	if (intent.label === "ambigua" || intent.confidence < t.minIntentConfidence) {
		if (intent.clarificationsAsked >= t.maxClarifications) {
			return rule("R06", [FICHA], derive("R06"));
		}
		return rule("R05", []);
	}
	if (intent.label === "fuera_de_alcance") {
		const tools =
			intent.outOfScopeTopic === "bloqueo_tarjeta"
				? [{ name: "tarjeta.bloquear", args: { motivo: "solicitud_cliente" } }]
				: [];
		return rule("R07", tools);
	}
	if (intent.label === "otro_reclamo") {
		return rule(
			"R08",
			[{ name: "reclamo.abrir", args: { tipo: "generico" } }],
			derive("R08"),
		);
	}

	// ---------------------------------------------------- 3 Identificar
	const { search } = facts;
	if (!search) {
		return {
			kind: "awaiting",
			ruleId: null,
			awaiting: "search",
			tools: [{ name: "txn.buscar" }],
			handoff: null,
			message: null,
		};
	}
	if (search.referencesForeignTransaction) {
		return rule("R09", [{ name: "log.seguridad" }]);
	}
	if (search.candidates === 0) {
		if (search.clarificationsAsked >= t.maxClarifications) {
			return rule("R10", [FICHA], derive("R10"));
		}
		return rule("R10", []);
	}
	if (search.candidates > 1 && !search.selected) {
		return rule("R11", []);
	}

	const txn = facts.transaction;
	if (!txn) {
		return {
			kind: "awaiting",
			ruleId: null,
			awaiting: "transaction",
			tools: [{ name: "txn.detalle" }],
			handoff: null,
			message: null,
		};
	}
	if (txn.ageDays > t.searchWindowDays) {
		return rule("R12", [FICHA], derive("R12"));
	}
	if (txn.hasOpenDispute) {
		return rule("R13", [{ name: "reclamo.consultar" }]);
	}
	if (txn.status === "Declined") {
		return rule("R14", [{ name: "txn.detalle" }]);
	}
	if (txn.status === "Reversed") {
		return rule("R16", [{ name: "txn.detalle" }]);
	}
	const highRisk = txn.fraudScore > t.fraudScoreAutoBlock;
	if (txn.status === "Pending" && !highRisk) {
		return rule("R15", [{ name: "seguimiento.programar" }]);
	}

	// ---------------------------------------------------- 4 Decidir
	const customer = facts.customer;

	if (intent.label === "cobro_indebido") {
		const withinLimit = txn.amountUsd <= t.autoReversalLimitUsd;
		if (
			txn.duplicateGapMinutes !== undefined &&
			txn.duplicateGapMinutes <= t.duplicateWindowMinutes
		) {
			if (withinLimit) {
				return rule("R23", [
					{ name: "comision.revertir", args: { motivo: "duplicado" } },
				]);
			}
			return rule(
				"R23",
				[{ name: "reclamo.abrir", args: { tipo: "cobro_indebido" } }],
				derive("R23"),
			);
		}
		if (txn.kind === "comision") {
			const firstOccurrence = (customer?.autoReversalsInPeriod ?? 0) === 0;
			if (withinLimit && firstOccurrence) {
				return rule("R21", [
					{ name: "comision.revertir", args: { motivo: "comision" } },
				]);
			}
			return rule(
				"R22",
				[{ name: "reclamo.abrir", args: { tipo: "cobro_indebido" } }],
				derive("R22"),
			);
		}
		// A purchase the customer recognizes but disputes the amount of: a
		// dispute with the merchant, never an automatic reversal.
		return rule(
			"R29",
			[{ name: "reclamo.abrir", args: { tipo: "cobro_indebido" } }],
			derive("R29"),
		);
	}

	// cargo_no_reconocido
	if (customer?.recognizesCharge === undefined) {
		return {
			kind: "awaiting",
			ruleId: null,
			awaiting: "customer.recognizesCharge",
			tools: [{ name: "txn.detalle" }],
			handoff: null,
			message: null,
		};
	}
	if (customer.recognizesCharge) {
		return rule("R17", [{ name: "caso.cerrar" }]);
	}
	if (highRisk) {
		return rule(
			"R18",
			[
				{ name: "tarjeta.bloquear", args: { motivo: "fraude" } },
				{ name: "reclamo.abrir", args: { tipo: "fraude" } },
				{ name: "handoff.crear_ficha", args: { prioridad: "alta" } },
			],
			derive("R18", { priority: "alta" }),
		);
	}
	const block: ToolCall[] = customer.acceptsBlock
		? [{ name: "tarjeta.bloquear", args: { motivo: "fraude" } }]
		: [];
	if (
		customer.unrecognizedCharges >= t.unrecognizedChargesForFraud ||
		customer.cardLostOrStolen
	) {
		return rule(
			"R19",
			[...block, { name: "reclamo.abrir", args: { tipo: "fraude" } }],
			derive("R19"),
		);
	}
	return rule(
		"R20",
		[{ name: "reclamo.abrir", args: { tipo: "disputa" } }, ...block],
		derive("R20"),
	);
}

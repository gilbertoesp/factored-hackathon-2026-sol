import { z } from "zod";
import raw from "./rules.json";

/**
 * The decision matrix as exported from docs/matriz_decision_es.xlsx by
 * backend/scripts/export_rules.py. Parsed with zod at import so a hand edit or
 * a stale export fails at boot, not halfway through a customer's case.
 */

export const RULE_IDS = [
	"R01",
	"R02",
	"R03",
	"R04",
	"R05",
	"R06",
	"R07",
	"R08",
	"R09",
	"R10",
	"R11",
	"R12",
	"R13",
	"R14",
	"R15",
	"R16",
	"R17",
	"R18",
	"R19",
	"R20",
	"R21",
	"R22",
	"R23",
	"R24",
	"R25",
	"R26",
	"R27",
	"R28",
	"R29",
] as const;

export type RuleId = (typeof RULE_IDS)[number];

const thresholdsSchema = z
	.object({
		fraudScoreAutoBlock: z.number().min(0).max(100),
		unrecognizedChargesForFraud: z.number().int().positive(),
		minIntentConfidence: z.number().gt(0).lt(1),
		maxClarifications: z.number().int().nonnegative(),
		searchWindowDays: z.number().int().positive(),
		dateToleranceDays: z.number().int().nonnegative(),
		autoReversalLimitUsd: z.number().nonnegative(),
		firstOccurrenceMonths: z.number().int().positive(),
		duplicateWindowMinutes: z.number().positive(),
		otpMaxAttempts: z.number().int().positive(),
		toolRetries: z.number().int().nonnegative(),
	})
	.strict();

const ruleSchema = z.object({
	id: z.enum(RULE_IDS),
	stage: z.string(),
	intent: z.string(),
	condition: z.string(),
	action: z.string(),
	tools: z.array(z.string()),
	verification: z.string().nullable(),
	message: z.string(),
	handoff: z.string(),
	queue: z.string().nullable(),
	metricOutcome: z.string(),
	testDataOrigin: z.string().nullable(),
	testCases: z.string().nullable(),
});

const policySchema = z.object({
	source: z.string(),
	note: z.string(),
	thresholds: thresholdsSchema,
	rules: z.array(ruleSchema).length(RULE_IDS.length),
});

export type Thresholds = z.infer<typeof thresholdsSchema>;
export type PolicyRule = z.infer<typeof ruleSchema>;

export interface Policy {
	thresholds: Thresholds;
	rules: Record<RuleId, PolicyRule>;
}

export function parsePolicy(input: unknown): Policy {
	const parsed = policySchema.parse(input);
	const rules = {} as Record<RuleId, PolicyRule>;
	for (const rule of parsed.rules) {
		rules[rule.id] = rule;
	}
	return { thresholds: parsed.thresholds, rules };
}

export const policy: Policy = parsePolicy(raw);

/**
 * Tool names a rule's "Herramientas" cell mentions, without arguments or
 * notes: "reclamo.abrir(tipo=fraude)" and "tarjeta.bloquear (si acepta)" both
 * reduce to their dotted name.
 */
export function toolNames(rule: PolicyRule): Set<string> {
	const names = new Set<string>();
	for (const cell of rule.tools) {
		for (const match of cell.matchAll(/[a-z_]+\.[a-z_]+/g)) {
			names.add(match[0]);
		}
	}
	return names;
}

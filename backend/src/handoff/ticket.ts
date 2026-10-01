import { z } from "zod";
import { RULE_IDS } from "../rules/policy";

/**
 * The ficha de derivación (R28): what the advisor receives instead of the
 * conversation. Today a complaint takes 7.2 minutes of handle time, mostly
 * re-asking what the customer already said; the ficha is what removes that.
 *
 * "Ningún campo obligatorio vacío" is enforced by the schema, not by review:
 * every required string is trimmed and non-empty, and the cross-field rules
 * below reject a ficha that is complete in shape but useless in content (a
 * fraud derivation without the transaction, a failed action not marked
 * pending).
 */

const text = z.string().trim().min(1);

/** Rules after which a specific transaction is known and must travel along. */
const RULES_WITH_TRANSACTION = new Set([
	"R12",
	"R18",
	"R19",
	"R20",
	"R22",
	"R23",
	"R29",
]);

const transactionSchema = z.object({
	transactionId: text,
	merchant: text,
	/** ISO date as the customer saw it (transaction_date). */
	date: z.string().date(),
	/** Original currency, which is what the customer recognizes. */
	amount: z.number(),
	currency: z.string().length(3),
	/** Normalized for thresholds: coalesce(amount_usd, amount if USD). */
	amountUsd: z.number().nonnegative(),
	status: z.enum(["Approved", "Declined", "Pending", "Reversed"]),
	fraudScore: z.number().min(0).max(100),
});

const actionSchema = z.object({
	tool: text,
	/** Only "verificada" may be reported to the customer as done (R24). */
	status: z.enum(["verificada", "fallida", "pendiente"]),
	/** Claim number, block reference, reversal id; null when nothing was created. */
	reference: text.nullable(),
	at: z.string().datetime({ offset: true }),
});

export const handoffTicketSchema = z
	.object({
		caseId: text,
		createdAt: z.string().datetime({ offset: true }),
		originRule: z.enum(RULE_IDS),
		queue: text,
		priority: z.enum(["normal", "alta"]),
		alert: z.enum(["verificacion"]).nullable(),
		language: z.enum(["es", "pt"]),
		channel: z.enum(["web", "whatsapp"]),
		/** Null only when the session never authenticated (R02). */
		customer: z
			.object({
				customerId: text,
				verifiedBy: z.literal("otp"),
				verifiedAt: z.string().datetime({ offset: true }),
			})
			.nullable(),
		request: z.object({
			/** The customer's first message, verbatim. */
			originalText: text,
			intent: text,
			intentConfidence: z.number().min(0).max(1),
			clarifications: z.array(text),
		}),
		transactions: z.array(transactionSchema),
		actions: z.array(actionSchema),
		pendingQuestions: z.array(text),
		/** One or two sentences the advisor reads first. */
		summary: text,
	})
	.strict()
	.superRefine((t, ctx) => {
		if (t.customer === null && t.originRule !== "R02") {
			ctx.addIssue({
				code: z.ZodIssueCode.custom,
				path: ["customer"],
				message: "only an unauthenticated session (R02) has no customer",
			});
		}
		if (
			RULES_WITH_TRANSACTION.has(t.originRule) &&
			t.transactions.length === 0
		) {
			ctx.addIssue({
				code: z.ZodIssueCode.custom,
				path: ["transactions"],
				message: `${t.originRule} derives about a known transaction`,
			});
		}
		if (t.originRule === "R18" && t.priority !== "alta") {
			ctx.addIssue({
				code: z.ZodIssueCode.custom,
				path: ["priority"],
				message: "a fraud block (R18) is always high priority",
			});
		}
		if (
			t.originRule === "R25" &&
			!t.actions.some((a) => a.status === "pendiente")
		) {
			ctx.addIssue({
				code: z.ZodIssueCode.custom,
				path: ["actions"],
				message: "R25 hands over an action the advisor must complete",
			});
		}
		if (t.originRule === "R26" && t.alert !== "verificacion") {
			ctx.addIssue({
				code: z.ZodIssueCode.custom,
				path: ["alert"],
				message: "R26 derives with a verification alert",
			});
		}
	});

export type HandoffTicket = z.infer<typeof handoffTicketSchema>;

/** Validates a ficha, returning issue paths only, never the content. */
export function parseTicket(
	input: unknown,
): { ok: true; value: HandoffTicket } | { ok: false; issues: string[] } {
	const result = handoffTicketSchema.safeParse(input);
	if (!result.success) {
		return {
			ok: false,
			issues: result.error.issues.map(
				(issue) => `${issue.path.join(".") || "ticket"}: ${issue.message}`,
			),
		};
	}
	return { ok: true, value: result.data };
}

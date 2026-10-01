import { z } from "zod";

/**
 * Wire contract of the single conversation API (B01) that the web chat and the
 * WhatsApp adapter both use. Proposed by the frontend (F02) so both sides can
 * build against it; the implementation behind it is B01.
 *
 * Shape decisions:
 * - The customer id never comes from the client after login. It lives in the
 *   session token, which the web app keeps in an httpOnly cookie.
 * - Structured answers (picking a transaction, yes/no) travel as typed fields,
 *   not free text, so the engine reads a verified fact instead of parsing
 *   "the second one" out of a message.
 * - A 401 on /messages means the session lapsed (R27). The client re-runs OTP
 *   and resends with the same conversationId; context is kept server-side.
 * - docs/contrato_conversacion.md has the same contract with examples.
 */

export const languageSchema = z.enum(["es", "pt"]);

// ------------------------------------------------------------ session (OTP)

/** POST /api/session/otp */
export const otpStartRequest = z
	.object({
		/** Customer reference typed at login; the demo uses test customers. */
		customerRef: z.string().trim().min(1).max(64),
		language: languageSchema,
	})
	.strict();

export const otpStartResponse = z.object({
	challengeId: z.string().min(1),
	/** Masked destination, e.g. "***1234". Never the full phone or email. */
	destinationHint: z.string(),
	/** Demo only: the simulated code, shown on screen. Absent in production. */
	demoCode: z.string().optional(),
});

/** POST /api/session/verify */
export const otpVerifyRequest = z
	.object({
		challengeId: z.string().min(1),
		code: z.string().regex(/^\d{4,8}$/),
	})
	.strict();

export const otpVerifyResponse = z.object({
	sessionToken: z.string().min(1),
	expiresAt: z.string().datetime({ offset: true }),
});

/**
 * Failed verify: 401 with attemptsLeft. At 0 the session is blocked (R02) and
 * the reply tells the customer where to go.
 */
export const otpVerifyFailure = z.object({
	status: z.enum(["invalid_code", "blocked"]),
	attemptsLeft: z.number().int().nonnegative(),
	message: z.string(),
});

// ------------------------------------------------------------ messages

/** POST /api/conversation/messages, Authorization: Bearer <sessionToken> */
export const messageRequest = z
	.object({
		/** Absent on the first message; the response assigns it. */
		conversationId: z.string().min(1).optional(),
		language: languageSchema,
		/** Free text. Optional when the turn is a selection or a confirmation. */
		text: z.string().trim().min(1).max(2000).optional(),
		/** Answer to a transaction_choices prompt (R11). */
		selection: z.object({ transactionId: z.string().min(1) }).optional(),
		/** Answer to a confirm prompt (R17 recognition, R19/R20 block offer). */
		confirmation: z
			.object({
				field: z.enum(["recognizesCharge", "acceptsBlock"]),
				value: z.boolean(),
			})
			.optional(),
	})
	.strict()
	.refine((m) => m.text || m.selection || m.confirmation, {
		message: "a turn carries text, a selection or a confirmation",
	});

export const transactionOption = z.object({
	transactionId: z.string().min(1),
	merchant: z.string(),
	date: z.string().date(),
	/** Original currency: what the customer sees on their statement. */
	amount: z.number(),
	currency: z.string().length(3),
	status: z.enum(["Approved", "Declined", "Pending", "Reversed"]),
});

export const uiPrompt = z.discriminatedUnion("type", [
	z.object({
		type: z.literal("transaction_choices"),
		options: z.array(transactionOption).min(1).max(3),
	}),
	z.object({
		type: z.literal("confirm"),
		field: z.enum(["recognizesCharge", "acceptsBlock"]),
		/** The transaction the question is about, shown as a card. */
		transaction: transactionOption.optional(),
	}),
]);

export const messageResponse = z.object({
	conversationId: z.string().min(1),
	reply: z.object({ text: z.string().min(1) }),
	/** Structured prompt the UI renders under the reply; null for plain text. */
	prompt: uiPrompt.nullable(),
	state: z.object({
		/** Rule that decided this turn, for traces and the demo; null if awaiting. */
		ruleId: z.string().nullable(),
		/** Set when the case was derived (R28): the ficha's case id and queue. */
		handoff: z
			.object({ caseId: z.string().min(1), queue: z.string().min(1) })
			.nullable(),
		/** No further input expected in this conversation. */
		ended: z.boolean(),
	}),
});

export type Language = z.infer<typeof languageSchema>;
export type OtpStartRequest = z.infer<typeof otpStartRequest>;
export type OtpStartResponse = z.infer<typeof otpStartResponse>;
export type OtpVerifyRequest = z.infer<typeof otpVerifyRequest>;
export type OtpVerifyResponse = z.infer<typeof otpVerifyResponse>;
export type OtpVerifyFailure = z.infer<typeof otpVerifyFailure>;
export type MessageRequest = z.infer<typeof messageRequest>;
export type MessageResponse = z.infer<typeof messageResponse>;
export type TransactionOption = z.infer<typeof transactionOption>;
export type UiPrompt = z.infer<typeof uiPrompt>;

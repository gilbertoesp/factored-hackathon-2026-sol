/**
 * Types of the conversation API, mirroring backend/src/conversation/contract.ts
 * (the zod source of truth). The backend validates every request, so the
 * browser side only needs the shapes.
 */
import type { Language } from "./i18n";

export interface TransactionOption {
	transactionId: string;
	merchant: string;
	date: string;
	amount: number;
	currency: string;
	status: "Approved" | "Declined" | "Pending" | "Reversed";
}

export type ConfirmField = "recognizesCharge" | "acceptsBlock";

export type UiPrompt =
	| { type: "transaction_choices"; options: TransactionOption[] }
	| { type: "confirm"; field: ConfirmField; transaction?: TransactionOption };

export interface MessageRequest {
	conversationId?: string;
	language: Language;
	text?: string;
	selection?: { transactionId: string };
	confirmation?: { field: ConfirmField; value: boolean };
}

export interface MessageResponse {
	conversationId: string;
	reply: { text: string };
	prompt: UiPrompt | null;
	state: {
		ruleId: string | null;
		handoff: { caseId: string; queue: string } | null;
		ended: boolean;
	};
}

export interface OtpStartResponse {
	challengeId: string;
	destinationHint: string;
	demoCode?: string;
}

export interface OtpVerifyFailure {
	status: "invalid_code" | "blocked";
	attemptsLeft: number;
	message: string;
}

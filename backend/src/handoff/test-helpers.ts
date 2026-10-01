import type { HandoffTicket } from "./ticket";

/** A complete, valid R18 ficha; tests override only what they are about. */
export function ticket(overrides: Partial<HandoffTicket> = {}): HandoffTicket {
	return {
		caseId: "case-001",
		createdAt: "2026-10-01T15:04:05-05:00",
		originRule: "R18",
		queue: "Analista de fraude",
		priority: "alta",
		alert: null,
		language: "es",
		channel: "web",
		customer: {
			customerId: "CUST-000123",
			verifiedBy: "otp",
			verifiedAt: "2026-10-01T15:01:00-05:00",
		},
		request: {
			originalText: "no reconozco un cobro del martes en Amazon",
			intent: "cargo_no_reconocido",
			intentConfidence: 0.94,
			clarifications: [],
		},
		transactions: [
			{
				transactionId: "TXN-9001",
				merchant: "AMAZON MKTPLACE",
				date: "2026-09-29",
				amount: 412000,
				currency: "COP",
				amountUsd: 98.6,
				status: "Approved",
				fraudScore: 74,
			},
		],
		actions: [
			{
				tool: "tarjeta.bloquear",
				status: "verificada",
				reference: "BLK-77",
				at: "2026-10-01T15:04:00-05:00",
			},
		],
		pendingQuestions: ["Confirmar si hay otros cargos no reconocidos"],
		summary: "Cargo no reconocido con fraud_score 74; tarjeta bloqueada.",
		...overrides,
	};
}

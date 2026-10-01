import { describe, expect, test } from "bun:test";
import {
	messageRequest,
	messageResponse,
	otpStartRequest,
	otpVerifyRequest,
} from "./contract";

describe("conversation contract", () => {
	test("a first message carries text and no conversation id", () => {
		expect(
			messageRequest.safeParse({
				language: "es",
				text: "no reconozco un cobro del martes",
			}).success,
		).toBe(true);
	});

	test("a turn must carry text, a selection or a confirmation", () => {
		expect(
			messageRequest.safeParse({ conversationId: "c1", language: "pt" })
				.success,
		).toBe(false);
		expect(
			messageRequest.safeParse({
				conversationId: "c1",
				language: "pt",
				selection: { transactionId: "TXN-1" },
			}).success,
		).toBe(true);
	});

	test("the client cannot send a customer id with a message", () => {
		expect(
			messageRequest.safeParse({
				language: "es",
				text: "hola",
				customerId: "CUST-9",
			}).success,
		).toBe(false);
	});

	test("OTP codes are digits only", () => {
		expect(
			otpVerifyRequest.safeParse({ challengeId: "x", code: "12ab" }).success,
		).toBe(false);
		expect(
			otpVerifyRequest.safeParse({ challengeId: "x", code: "482913" }).success,
		).toBe(true);
	});

	test("login rejects a blank customer reference", () => {
		expect(
			otpStartRequest.safeParse({ customerRef: "  ", language: "es" }).success,
		).toBe(false);
	});

	test("transaction choices are capped at the top 3 (R11)", () => {
		const option = {
			transactionId: "T",
			merchant: "M",
			date: "2026-09-29",
			amount: 10,
			currency: "USD",
			status: "Approved",
		};
		const response = (n: number) => ({
			conversationId: "c1",
			reply: { text: "¿Cuál es?" },
			prompt: {
				type: "transaction_choices",
				options: Array.from({ length: n }, (_, i) => ({
					...option,
					transactionId: `T${i}`,
				})),
			},
			state: { ruleId: "R11", handoff: null, ended: false },
		});
		expect(messageResponse.safeParse(response(3)).success).toBe(true);
		expect(messageResponse.safeParse(response(4)).success).toBe(false);
	});
});

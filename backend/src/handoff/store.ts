import type { HandoffTicket } from "./ticket";

/**
 * Persistence for fichas. `case_id` is the idempotency key (Herramientas
 * sheet): a retried handoff.crear_ficha returns the ficha already stored
 * instead of creating a second one, so a timeout between write and response
 * never sends the same case to two advisors.
 */
export interface HandoffStore {
	save(
		ticket: HandoffTicket,
	): Promise<{ created: boolean; ticket: HandoffTicket }>;
	get(caseId: string): Promise<HandoffTicket | null>;
	/** Newest first, for the advisor view. */
	listByQueue(queue: string): Promise<HandoffTicket[]>;
}

export function createMemoryHandoffStore(): HandoffStore {
	const tickets = new Map<string, HandoffTicket>();
	return {
		async save(ticket) {
			const existing = tickets.get(ticket.caseId);
			if (existing) {
				return { created: false, ticket: existing };
			}
			tickets.set(ticket.caseId, ticket);
			return { created: true, ticket };
		},
		async get(caseId) {
			return tickets.get(caseId) ?? null;
		},
		async listByQueue(queue) {
			return [...tickets.values()]
				.filter((t) => t.queue === queue)
				.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
		},
	};
}

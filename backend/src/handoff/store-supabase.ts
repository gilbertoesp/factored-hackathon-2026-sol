import type { SupabaseClient } from "@supabase/supabase-js";
import type { HandoffStore } from "./store";
import type { HandoffTicket } from "./ticket";

const TABLE = "handoff_tickets";

interface HandoffRow {
	case_id: string;
	origin_rule: string;
	queue: string;
	priority: string;
	language: string;
	customer_id: string | null;
	ticket: HandoffTicket;
	created_at: string;
}

/**
 * Fichas in public.handoff_tickets (migration 0002). The client must use the
 * service role key: the table has RLS on and no policy for anon or
 * authenticated, by design.
 *
 * Idempotency is the primary key on case_id. The insert ignores a duplicate
 * instead of failing, and a retry then reads back the ficha already stored, so
 * the same contract as the memory store holds: the first write wins.
 */
export function createSupabaseHandoffStore(
	client: SupabaseClient,
): HandoffStore {
	const table = () => client.from(TABLE);

	async function get(caseId: string): Promise<HandoffTicket | null> {
		const { data, error } = await table()
			.select("ticket")
			.eq("case_id", caseId)
			.maybeSingle();
		if (error) throw storeError("get", error);
		return (data?.ticket as HandoffTicket | undefined) ?? null;
	}

	async function listWhere(queue?: string): Promise<HandoffTicket[]> {
		let query = table().select("ticket");
		if (queue !== undefined) query = query.eq("queue", queue);
		const { data, error } = await query.order("created_at", {
			ascending: false,
		});
		if (error) throw storeError("list", error);
		return (data ?? []).map((row) => row.ticket as HandoffTicket);
	}

	return {
		async save(ticket) {
			const { data, error } = await table()
				.upsert(toRow(ticket), {
					onConflict: "case_id",
					ignoreDuplicates: true,
				})
				.select("ticket");
			if (error) throw storeError("save", error);
			if (data && data.length > 0) {
				return { created: true, ticket };
			}
			const existing = await get(ticket.caseId);
			if (!existing) {
				// Ignored as a duplicate yet not readable: a policy or grant is
				// wrong, and pretending the write happened would lose the case.
				throw new Error(
					`handoff store: case ${ticket.caseId} neither inserted nor found`,
				);
			}
			return { created: false, ticket: existing };
		},
		get,
		listByQueue: (queue) => listWhere(queue),
		list: () => listWhere(),
	};
}

function toRow(ticket: HandoffTicket): HandoffRow {
	return {
		case_id: ticket.caseId,
		origin_rule: ticket.originRule,
		queue: ticket.queue,
		priority: ticket.priority,
		language: ticket.language,
		customer_id: ticket.customer?.customerId ?? null,
		ticket,
		// The ficha's own timestamp, so the advisor view sorts by when the case
		// was derived, not by when a retry happened to land.
		created_at: ticket.createdAt,
	};
}

// The PostgREST message and code only. Details and hints can echo row values,
// and a ficha holds the customer id.
function storeError(op: string, error: { code?: string; message: string }) {
	return new Error(
		`handoff store ${op} failed: ${error.code ?? "unknown"} ${error.message}`,
	);
}

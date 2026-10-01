-- Fichas de derivación (R28): what the advisor receives instead of the chat.
--
-- The full ficha is stored as jsonb, validated by handoffTicketSchema in
-- backend/src/handoff/ticket.ts before it is written. The columns pulled out
-- of it are the ones the advisor view filters and sorts on; the checks repeat
-- the schema's non-empty rule so a write that skips the backend still cannot
-- store a ficha an advisor cannot act on.

create table if not exists public.handoff_tickets (
	-- Idempotency key of handoff.crear_ficha: a retried write is a no-op.
	case_id text primary key,
	origin_rule text not null,
	queue text not null,
	priority text not null,
	language text not null,
	customer_id text,
	ticket jsonb not null,
	created_at timestamptz not null default now(),
	constraint handoff_tickets_origin_rule check (origin_rule ~ '^(R(0[1-9]|1[0-9]|2[0-8])|SIN_REGLA)$'),
	constraint handoff_tickets_queue_not_blank check (length(trim(queue)) > 0),
	constraint handoff_tickets_priority check (priority in ('normal', 'alta')),
	constraint handoff_tickets_language check (language in ('es', 'pt')),
	-- Only an unauthenticated session (R02) derives without a customer.
	constraint handoff_tickets_customer check (customer_id is not null or origin_rule = 'R02'),
	constraint handoff_tickets_ticket_matches check (
		ticket ->> 'caseId' = case_id
		and ticket ->> 'originRule' = origin_rule
		and ticket ->> 'queue' = queue
		and ticket ->> 'priority' = priority
	)
);

create index if not exists handoff_tickets_queue_created
	on public.handoff_tickets (queue, created_at desc);

-- Service role only, like the other system-written tables. Fichas hold the
-- customer id and transaction detail; advisors read them through the backend,
-- never with an anon or authenticated key.
alter table public.handoff_tickets enable row level security;

revoke all on public.handoff_tickets from anon;
revoke all on public.handoff_tickets from authenticated;

comment on table public.handoff_tickets is
	'Fichas de derivación (R28). service_role only; validated by handoffTicketSchema before insert.';

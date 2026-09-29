-- WhatsApp webhook storage: RLS policies for the tables backing the two seams.
--
-- The compose stack runs a bare postgres:16-alpine, which has no auth schema, so
-- these policies cannot be exercised locally. They apply to a hosted Supabase
-- project, where `auth.users` and the `auth.uid()` helper exist.

-- ---------------------------------------------------------------------------
-- Event tables: service_role only.
--
-- These hold phone numbers and message metadata written by the webhook and
-- never read by a user-facing client. RLS is enabled and every privilege is
-- revoked from anon and authenticated, which is what makes the table
-- unreachable to them. service_role has BYPASSRLS and never evaluates policies,
-- so writing policies for it would be dead SQL.
-- ---------------------------------------------------------------------------

create table if not exists public.webhook_events (
	id bigint primary key generated always as identity,
	entry_id text not null,
	message_id text not null,
	field text not null,
	received_at timestamptz not null default now(),
	constraint webhook_events_unique_delivery unique (entry_id, field, message_id)
);

alter table public.webhook_events enable row level security;

revoke all on public.webhook_events from anon;
revoke all on public.webhook_events from authenticated;

comment on table public.webhook_events is
	'Inbound notification metadata. service_role only; no anon or authenticated policy by design.';

create table if not exists public.delegation_grants (
	id text primary key,
	subject text not null,
	scope text not null,
	issued_at timestamptz not null default now(),
	expires_at timestamptz not null
);

alter table public.delegation_grants enable row level security;

revoke all on public.delegation_grants from anon;
revoke all on public.delegation_grants from authenticated;

comment on table public.delegation_grants is
	'Issued RFC 8693 delegation grants. service_role only; no anon or authenticated policy by design.';

-- ---------------------------------------------------------------------------
-- Conversation tables: per-user policies.
--
-- A conversation belongs to the end user who owns the WhatsApp thread, matched
-- on `wa_id`. The comparison is cast because auth.uid() is uuid and wa_id is
-- text; without the cast Postgres would compare uuid to text and silently
-- refuse every row rather than leak one.
-- ---------------------------------------------------------------------------

create table if not exists public.whatsapp_conversations (
	id uuid primary key default gen_random_uuid(),
	wa_id text not null,
	phone_number_id text not null,
	created_at timestamptz not null default now()
);

alter table public.whatsapp_conversations enable row level security;

create policy "Users can read their own conversations"
	on public.whatsapp_conversations
	for select
	to authenticated
	using ((select auth.uid())::text = wa_id);

create policy "Users can start their own conversations"
	on public.whatsapp_conversations
	for insert
	to authenticated
	with check ((select auth.uid())::text = wa_id);

-- No update or delete policy: a user may open a thread but not rewrite or
-- remove it. service_role still bypasses RLS for lifecycle work.

create table if not exists public.whatsapp_messages (
	id uuid primary key default gen_random_uuid(),
	conversation_id uuid not null
		references public.whatsapp_conversations (id) on delete cascade,
	sender text not null,
	body text,
	sent_at timestamptz not null default now()
);

alter table public.whatsapp_messages enable row level security;

-- The message policy resolves ownership through the parent conversation rather
-- than storing wa_id again, so there is one place that decides who a thread
-- belongs to.
create policy "Users can read messages in their own conversations"
	on public.whatsapp_messages
	for select
	to authenticated
	using (
		exists (
			select 1
			from public.whatsapp_conversations c
			where c.id = whatsapp_messages.conversation_id
				and (select auth.uid())::text = c.wa_id
		)
	);

create policy "Users can send messages in their own conversations"
	on public.whatsapp_messages
	for insert
	to authenticated
	with check (
		exists (
			select 1
			from public.whatsapp_conversations c
			where c.id = whatsapp_messages.conversation_id
				and (select auth.uid())::text = c.wa_id
		)
	);

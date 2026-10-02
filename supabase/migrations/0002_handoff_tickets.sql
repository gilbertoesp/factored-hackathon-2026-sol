-- 0002_handoff_tickets: disputes + fichas de derivación (handoff) con monto_usd y fraud_score.
-- Idempotente: puede ejecutarse varias veces. No toca silver.complaints.
BEGIN;

-- 1. monto_usd sobre las transacciones: COALESCE(amount_usd origen, amount) en USD;
--    en otras monedas, el amount_usd convertido por el pipeline gold.
CREATE OR REPLACE VIEW gold.transactions_monto_usd AS
SELECT f.*,
       CASE WHEN f.currency = 'USD' THEN COALESCE(f.amount_usd_source, f.amount)
            ELSE f.amount_usd END AS monto_usd
FROM gold.fact_transactions_usd f;

-- 2. disputes: registro propio de reclamos/fichas (independiente de complaints).
CREATE TABLE IF NOT EXISTS public.disputes (
    dispute_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id     text NOT NULL,
    transaction_id  text,
    intent          text NOT NULL CHECK (intent IN
                      ('cargo_no_reconocido','cobro_indebido','otro_reclamo','ambigua','fuera_de_alcance')),
    subtype         text CHECK (subtype IN ('comision','duplicado','compra','bloqueo_tarjeta','otro')),
    confidence      numeric(4,3) CHECK (confidence BETWEEN 0 AND 1),
    language        text,
    status          text NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open','resolved','handed_off','closed')),
    monto_usd       numeric(18,4) CHECK (monto_usd >= 0),
    fraud_score     numeric(5,2)  CHECK (fraud_score BETWEEN 0 AND 100),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS disputes_customer_idx    ON public.disputes (customer_id);
CREATE INDEX IF NOT EXISTS disputes_transaction_idx ON public.disputes (transaction_id);

-- 3. handoff_tickets: ficha de derivación a un agente humano.
CREATE TABLE IF NOT EXISTS public.handoff_tickets (
    ticket_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dispute_id   uuid NOT NULL REFERENCES public.disputes(dispute_id),
    customer_id  text NOT NULL,
    reason       text NOT NULL,
    summary      jsonb NOT NULL DEFAULT '{}'::jsonb,
    status       text NOT NULL DEFAULT 'open'
                   CHECK (status IN ('open','assigned','resolved','cancelled')),
    assigned_to  text,
    monto_usd    numeric(18,4) CHECK (monto_usd >= 0),
    fraud_score  numeric(5,2)  CHECK (fraud_score BETWEEN 0 AND 100),
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS handoff_tickets_dispute_idx ON public.handoff_tickets (dispute_id);
CREATE INDEX IF NOT EXISTS handoff_tickets_status_idx  ON public.handoff_tickets (status);

-- 4. Historial de cambios de cada ficha.
CREATE TABLE IF NOT EXISTS public.handoff_ticket_history (
    history_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id    uuid NOT NULL REFERENCES public.handoff_tickets(ticket_id),
    from_status  text,
    to_status    text NOT NULL,
    changed_by   text,
    monto_usd    numeric(18,4) CHECK (monto_usd >= 0),
    fraud_score  numeric(5,2)  CHECK (fraud_score BETWEEN 0 AND 100),
    note         text,
    changed_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS handoff_history_ticket_idx ON public.handoff_ticket_history (ticket_id, changed_at);

COMMIT;

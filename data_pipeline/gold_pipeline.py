#!/usr/bin/env python3
"""Capa gold (silver -> gold).

Tablas creadas en el esquema `gold` (se recrean en cada corrida):
  fact_transactions_usd  silver.transactions + amount_usd exacto (JOIN por fecha y moneda origen).
  gold_customer_360      1 fila por cliente: perfil + productos + quejas.

Entorno: DATABASE_URL (obligatoria). Opcionales: GOLD_SCHEMA, SILVER_SCHEMA, STEPS=tabla1,tabla2.
"""
import logging
import os
import sys
import time

from sqlalchemy import create_engine

SILVER = os.getenv("SILVER_SCHEMA", "silver")
GOLD = os.getenv("GOLD_SCHEMA", "gold")
log = logging.getLogger("gold_pipeline")

# ---------------------------------------------------------------- 1. transacciones en USD
# exchange_rate está expresada como 1 unidad de source_currency = rate USD (validado: multiplicar).
# Si falta la tasa del día se usa la más cercana en fecha (fx_fallback = true).
SQL_FACT = f"""
CREATE TABLE {GOLD}.fact_transactions_usd AS
WITH usd AS (SELECT date, source_currency, exchange_rate FROM {SILVER}.daily_exchange_rates WHERE target_currency = 'USD'),
j AS (
  SELECT t.*, r.exchange_rate AS rate_exact
  FROM {SILVER}.transactions t
  LEFT JOIN usd r ON r.date = t.transaction_date::date AND r.source_currency = t.currency
)
SELECT j.transaction_id, j.transaction_date, j.process_date, j.customer_id, j.product_id, j.branch_id,
       j.transaction_type, j.transaction_category, j.channel, j.transaction_status, j.response_code,
       j.merchant_name, j.merchant_category, j.transaction_country, j.transaction_city,
       j.amount, j.currency,
       CASE WHEN j.currency = 'USD' THEN 1 ELSE COALESCE(j.rate_exact, fb.exchange_rate) END AS exchange_rate,
       CASE WHEN j.currency = 'USD' THEN j.amount
            ELSE round(j.amount * COALESCE(j.rate_exact, fb.exchange_rate), 4) END AS amount_usd,
       (j.currency <> 'USD' AND j.rate_exact IS NULL) AS fx_fallback,
       j.amount_usd AS amount_usd_source,
       j.is_fraud, j.fraud_score, j.latitude, j.longitude
FROM j
LEFT JOIN LATERAL (
  SELECT u.exchange_rate FROM usd u
  WHERE j.currency <> 'USD' AND j.rate_exact IS NULL AND u.source_currency = j.currency
  ORDER BY abs(u.date - j.transaction_date::date) LIMIT 1
) fb ON true
"""

# ---------------------------------------------------------------- 2. customer 360
SQL_C360 = f"""
CREATE TABLE {GOLD}.gold_customer_360 AS
WITH fx AS (  -- última tasa a USD por moneda
  SELECT DISTINCT ON (source_currency) source_currency, exchange_rate
  FROM {SILVER}.daily_exchange_rates WHERE target_currency = 'USD' ORDER BY source_currency, date DESC
),
prod AS (
  SELECT p.customer_id,
         count(*) AS n_products,
         count(*) FILTER (WHERE p.product_status ILIKE 'active') AS n_active_products,
         count(DISTINCT p.product_type) AS n_product_types,
         string_agg(DISTINCT p.product_type, ', ' ORDER BY p.product_type) AS product_types,
         round(sum(p.current_balance * COALESCE(f.exchange_rate, CASE WHEN p.currency = 'USD' THEN 1 END)), 2) AS total_balance_usd,
         max(p.days_past_due) AS max_days_past_due,
         jsonb_agg(jsonb_build_object('product_id', p.product_id, 'type', p.product_type,
                   'number', '****' || right(p.product_number, 4), 'currency', p.currency,
                   'balance', p.current_balance, 'status', p.product_status,
                   'days_past_due', p.days_past_due) ORDER BY p.opening_date) AS products
  FROM {SILVER}.products p LEFT JOIN fx f ON f.source_currency = p.currency
  GROUP BY p.customer_id
),
comp AS (
  SELECT customer_id,
         count(*) AS complaint_count,
         count(*) FILTER (WHERE status IN ('Open', 'In Process', 'Escalated')) AS open_complaint_count,
         count(*) FILTER (WHERE sla_breached) AS sla_breached_count,
         max(creation_date) AS last_complaint_at,
         (array_agg(category ORDER BY creation_date DESC))[1] AS last_complaint_category,
         bool_or(COALESCE(is_repeat_complainer, false)) AS flagged_repeat_source
  FROM {SILVER}.complaints GROUP BY customer_id
)
SELECT c.customer_id, c.first_name || ' ' || c.last_name AS full_name, c.gender, c.date_of_birth,
       extract(year FROM age(current_date, c.date_of_birth))::int AS age,
       c.city, c.state, c.country, c.segment, c.customer_status, c.registration_date,
       c.credit_score, c.estimated_monthly_income, c.occupation, c.marital_status, c.education_level,
       c.accepts_marketing,
       COALESCE(p.n_products, 0) AS n_products, COALESCE(p.n_active_products, 0) AS n_active_products,
       COALESCE(p.n_product_types, 0) AS n_product_types, p.product_types, p.total_balance_usd,
       p.max_days_past_due, COALESCE(p.products, '[]'::jsonb) AS products,
       COALESCE(k.complaint_count, 0) AS complaint_count,
       COALESCE(k.open_complaint_count, 0) AS open_complaint_count,
       COALESCE(k.sla_breached_count, 0) AS sla_breached_count,
       k.last_complaint_at, k.last_complaint_category,
       (COALESCE(k.complaint_count, 0) >= 2 OR COALESCE(k.flagged_repeat_source, false)) AS is_repeat_complainer
FROM {SILVER}.customers c
LEFT JOIN prod p ON p.customer_id = c.customer_id
LEFT JOIN comp k ON k.customer_id = c.customer_id
"""


def checks(engine):
    with engine.connect() as c:
        q = lambda s: c.exec_driver_sql(s).scalar()
        n_s, n_f = q(f"SELECT count(*) FROM {SILVER}.transactions"), q(f"SELECT count(*) FROM {GOLD}.fact_transactions_usd")
        no_fx = q(f"SELECT count(*) FROM {GOLD}.fact_transactions_usd WHERE amount_usd IS NULL")
        fb = q(f"SELECT count(*) FROM {GOLD}.fact_transactions_usd WHERE fx_fallback")
        dev = q(f"SELECT max(abs(amount_usd / NULLIF(amount_usd_source, 0) - 1)) FROM {GOLD}.fact_transactions_usd "
                f"WHERE amount_usd_source IS NOT NULL AND currency <> 'USD'")
        n_c, n_cs = q(f"SELECT count(*) FROM {SILVER}.customers"), q(f"SELECT count(*) FROM {GOLD}.gold_customer_360")
        rep = q(f"SELECT count(*) FROM {GOLD}.gold_customer_360 WHERE is_repeat_complainer")
    log.info("fact: silver=%d gold=%d | sin amount_usd=%d | con tasa de respaldo=%d | desvío máx vs amount_usd fuente=%.3f",
             n_s, n_f, no_fx, fb, dev or 0)
    log.info("customer_360: silver=%d gold=%d | is_repeat_complainer=%d", n_c, n_cs, rep)
    assert n_s == n_f and n_c == n_cs and no_fx == 0, "falló verificación de gold"


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("gold_pipeline.log", encoding="utf-8")])
    if not os.getenv("DATABASE_URL"):
        log.error("Falta DATABASE_URL")
        return 1
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True, connect_args={"connect_timeout": 15})
    with engine.begin() as c:
        c.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {GOLD}")
    steps = [("fact_transactions_usd", SQL_FACT, ["transaction_id"], ["customer_id"]),
             ("gold_customer_360", SQL_C360, ["customer_id"], [])]
    only = [x for x in os.getenv("STEPS", "").split(",") if x]  # STEPS="a,b": reconstruye solo esas tablas
    for name, sql, pk, idx in steps:
        if only and name not in only:
            continue
        t0 = time.time()
        log.info("[%s] construyendo...", name)
        with engine.begin() as c:
            c.exec_driver_sql("SET LOCAL statement_timeout = 0")
            c.exec_driver_sql("SET LOCAL work_mem = '256MB'")
            c.exec_driver_sql(f"DROP TABLE IF EXISTS {GOLD}.{name}")
            c.exec_driver_sql(sql.replace("%", "%%"))  # psycopg2 interpreta % (p.ej. format('%s'))
            c.exec_driver_sql(f"ALTER TABLE {GOLD}.{name} ADD PRIMARY KEY ({', '.join(pk)})")
            for col in idx:
                c.exec_driver_sql(f"CREATE INDEX ON {GOLD}.{name} ({col})")
        c = engine.connect()
        n = c.exec_driver_sql(f"SELECT count(*) FROM {GOLD}.{name}").scalar()
        c.close()
        log.info("[%s] %d filas (%.1fs)", name, n, time.time() - t0)
    checks(engine)
    return 0


if __name__ == "__main__":
    sys.exit(main())

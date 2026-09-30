#!/usr/bin/env python3
"""Capa gold (silver -> gold) para ML/LLM.

Tablas creadas en el esquema `gold` (se recrean en cada corrida):
  fact_transactions_usd  silver.transactions + amount_usd exacto (JOIN por fecha y moneda origen).
  gold_customer_360      1 fila por cliente: perfil + productos + quejas + texto `llm_context`.
  gold_dispute_features  1 fila por cliente con transacciones: solo columnas numéricas, sin NULL.

Además exporta el tensor para el Autoencoder (PyTorch) a EXPORT_DIR (default gold_export/):
  dispute_features.npz            X (float32, N x D, estandarizado), customer_ids, columns
  dispute_features_manifest.json  columnas, transformaciones y parámetros de escala (mean/std)

Uso en PyTorch:
  d = np.load("gold_export/dispute_features.npz", allow_pickle=True)
  X = torch.from_numpy(d["X"])          # listo para TensorDataset / DataLoader

Entorno: DATABASE_URL (obligatoria). Opcionales: GOLD_SCHEMA, SILVER_SCHEMA, EXPORT_DIR, SKIP_EXPORT=1, STEPS=tabla1,tabla2.
"""
import json
import logging
import os
import sys
import time

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

SILVER = os.getenv("SILVER_SCHEMA", "silver")
GOLD = os.getenv("GOLD_SCHEMA", "gold")
EXPORT_DIR = os.getenv("EXPORT_DIR", "gold_export")
log = logging.getLogger("gold_pipeline")

MERCHANT_CATS = ["Food", "Services", "Other", "Transport", "Entertainment", "Health"]
TXN_TYPES = ["Purchase", "Payment", "Withdrawal", "Transfer", "Deposit", "Adjustment"]
SPEND_TYPES = ["Purchase", "Payment", "Withdrawal"]

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
       (COALESCE(k.complaint_count, 0) >= 2 OR COALESCE(k.flagged_repeat_source, false)) AS is_repeat_complainer,
       format('Cliente %s (%s, %s, segmento %s, estado %s). %s. Ingreso mensual estimado: %s. Score crediticio: %s. '
              || 'Productos: %s%s. Quejas: %s (abiertas: %s)%s.',
              c.customer_id, c.first_name || ' ' || c.last_name, COALESCE(c.country, 'país n/d'),
              COALESCE(c.segment, 'n/d'), COALESCE(c.customer_status, 'n/d'),
              COALESCE(c.occupation, 'ocupación n/d'),
              COALESCE(c.estimated_monthly_income::text, 'n/d'), COALESCE(c.credit_score::text, 'n/d'),
              COALESCE(p.n_products, 0), COALESCE(' (' || p.product_types || ', saldo total USD ' || p.total_balance_usd || ')', ''),
              COALESCE(k.complaint_count, 0), COALESCE(k.open_complaint_count, 0),
              CASE WHEN COALESCE(k.complaint_count, 0) >= 2 OR COALESCE(k.flagged_repeat_source, false)
                   THEN '; reclamante recurrente' ELSE '' END) AS llm_context
FROM {SILVER}.customers c
LEFT JOIN prod p ON p.customer_id = c.customer_id
LEFT JOIN comp k ON k.customer_id = c.customer_id
"""


# ---------------------------------------------------------------- 3. features de disputas
def features_sql():
    """Agrega por cliente. Montos sobre transacciones Approved; conteos/tasas sobre todas."""
    ap = "transaction_status = 'Approved'"
    usd = f"sum(amount_usd) FILTER (WHERE {ap} AND transaction_type = '%s')"
    total_ap = f"NULLIF(sum(amount_usd) FILTER (WHERE {ap}), 0)"
    spend = " + ".join(f"COALESCE({usd % t}, 0)" for t in SPEND_TYPES)
    deposit = f"COALESCE({usd % 'Deposit'}, 0)"
    cols = [
        "customer_id",
        "count(*)::float8 AS n_txn",
        f"COALESCE(sum(amount_usd) FILTER (WHERE {ap}), 0)::float8 AS total_usd",
        f"COALESCE(avg(amount_usd) FILTER (WHERE {ap}), 0)::float8 AS avg_usd",
        f"COALESCE(stddev_samp(amount_usd) FILTER (WHERE {ap}), 0)::float8 AS std_usd",
        f"COALESCE(max(amount_usd) FILTER (WHERE {ap}), 0)::float8 AS max_usd",
        f"({spend})::float8 AS spend_usd",
        f"({spend})::float8 / GREATEST(1, (max(transaction_date)::date - min(transaction_date)::date) / 30.4) AS monthly_spend_usd",
        f"COALESCE(({spend}) / NULLIF(({spend}) + {deposit}, 0), 0)::float8 AS spend_ratio",
    ]
    cols += [f"COALESCE({usd % t} / {total_ap}, 0)::float8 AS share_{t.lower()}_usd" for t in TXN_TYPES]
    cols += [f"(count(*) FILTER (WHERE merchant_category = '{m}'))::float8 / count(*) AS freq_{m.lower()}" for m in MERCHANT_CATS]
    cols += ["(count(*) FILTER (WHERE merchant_category IS NULL))::float8 / count(*) AS freq_no_merchant"]
    cols += [f"(count(*) FILTER (WHERE transaction_status = '{s}'))::float8 / count(*) AS rate_{s.lower()}"
             for s in ("Declined", "Reversed", "Pending")]
    cols += [
        "(count(*) FILTER (WHERE currency <> 'USD'))::float8 / count(*) AS share_foreign_currency",
        "(count(*) FILTER (WHERE extract(hour FROM transaction_date) < 6))::float8 / count(*) AS night_txn_share",
        "count(DISTINCT merchant_category)::float8 AS n_merchant_categories",
        # fraud_score: los NULL (20 %) se imputan con la media global y se deja el indicador de faltantes
        "COALESCE(avg(fraud_score), (SELECT avg FROM g))::float8 AS fraud_score_avg",
        "COALESCE(max(fraud_score), (SELECT avg FROM g))::float8 AS fraud_score_max",
        "COALESCE(stddev_samp(fraud_score), 0)::float8 AS fraud_score_std",
        "(count(*) FILTER (WHERE fraud_score IS NULL))::float8 / count(*) AS fraud_score_missing_rate",
        # etiqueta (NO es feature del autoencoder): útil para evaluar el detector de anomalías
        "COALESCE(bool_or(is_fraud), false) AS label_has_fraud",
    ]
    return (f"CREATE TABLE {GOLD}.gold_dispute_features AS "
            f"WITH g AS (SELECT avg(fraud_score) AS avg FROM {GOLD}.fact_transactions_usd) "
            f"SELECT {', '.join(cols)} FROM {GOLD}.fact_transactions_usd "
            f"WHERE customer_id IS NOT NULL GROUP BY customer_id")


LOG1P_COLS = ["n_txn", "total_usd", "avg_usd", "std_usd", "max_usd", "spend_usd", "monthly_spend_usd",
              "n_merchant_categories"]
NON_FEATURES = ["customer_id", "label_has_fraud"]


def export_tensor(engine):
    df = pd.read_sql(f"SELECT * FROM {GOLD}.gold_dispute_features ORDER BY customer_id", engine)
    feats = [c for c in df.columns if c not in NON_FEATURES]
    x = df[feats].astype("float64")
    if x.isna().any().any() or not np.isfinite(x.to_numpy()).all():
        raise RuntimeError("gold_dispute_features contiene NULL/inf; no se exporta")
    x[LOG1P_COLS] = np.log1p(x[LOG1P_COLS])  # montos y conteos muy sesgados
    mean, std = x.mean(), x.std(ddof=0).replace(0, 1.0)
    z = ((x - mean) / std).clip(-5, 5).astype("float32")
    os.makedirs(EXPORT_DIR, exist_ok=True)
    np.savez_compressed(os.path.join(EXPORT_DIR, "dispute_features.npz"), X=z.to_numpy(),
                        customer_ids=df["customer_id"].to_numpy(dtype=object),
                        labels=df["label_has_fraud"].to_numpy(dtype=bool), columns=np.array(feats))
    manifest = dict(rows=len(z), n_features=len(feats), columns=feats, log1p=LOG1P_COLS,
                    scaler=dict(mean=mean.to_dict(), std=std.to_dict(), clip=5),
                    note="X = clip((log1p(col) - mean) / std, -5, 5), float32. labels no es feature.")
    with open(os.path.join(EXPORT_DIR, "dispute_features_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    log.info("Export: X=%s float32 -> %s/", z.shape, EXPORT_DIR)
    return z


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
        nnull = q(f"SELECT count(*) FROM {GOLD}.gold_dispute_features t "
                  f"WHERE EXISTS (SELECT 1 FROM jsonb_each(to_jsonb(t)) e WHERE e.value = 'null'::jsonb)")
    log.info("fact: silver=%d gold=%d | sin amount_usd=%d | con tasa de respaldo=%d | desvío máx vs amount_usd fuente=%.3f",
             n_s, n_f, no_fx, fb, dev or 0)
    log.info("customer_360: silver=%d gold=%d | is_repeat_complainer=%d | features con NULL=%d", n_c, n_cs, rep, nnull)
    assert n_s == n_f and n_c == n_cs and no_fx == 0 and nnull == 0, "falló verificación de gold"


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
             ("gold_customer_360", SQL_C360, ["customer_id"], []),
             ("gold_dispute_features", features_sql(), ["customer_id"], [])]
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
    if os.getenv("SKIP_EXPORT") != "1":
        export_tensor(engine)
    return 0


if __name__ == "__main__":
    sys.exit(main())

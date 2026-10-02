#!/usr/bin/env python3
"""Pipeline de calidad bronze -> silver (+ silver_quarantine) con Great Expectations.

Por cada tabla, en orden de dependencias:
  1. Normaliza (trim, ''/null/nan -> NULL) y castea a tipos reales (cast seguro).
  2. Deduplica por clave primaria conservando la fila más reciente
     (process_date / last_updated, desempate por _ingested_at).
  3. Envía a `silver.silver_quarantine` toda fila con: duplicado perdedor, nulo/valor
     inválido en columna NOT NULL, o clave foránea sin padre en la tabla silver del padre
     (la cuarentena se propaga en cascada a las tablas hijas).
  4. Escribe el resto en `silver.<tabla>` con PRIMARY KEY.
  5. Valida silver con Great Expectations (unicidad, not-null, FKs, conciliación de filas).

Las columnas anulables se mantienen en NULL (no se imputa 0 por defecto, para no fabricar
valores "seguros" p.ej. fraud_score=0). Para imputar: IMPUTE_ZERO="transactions.fraud_score,...".

Entorno: DATABASE_URL (obligatoria). Opcionales: BRONZE_SCHEMA, SILVER_SCHEMA, TABLES="a,b",
IMPUTE_ZERO, SKIP_GE=1.
"""
import json
import logging
import os
import sys
import time

from sqlalchemy import create_engine

os.environ.setdefault("TQDM_DISABLE", "1")  # sin barras de progreso de GE en los logs

BRONZE = os.getenv("BRONZE_SCHEMA", "bronze")
SILVER = os.getenv("SILVER_SCHEMA", "silver")
QUAR = "silver_quarantine"
IMPUTE_ZERO = {tuple(x.strip().split(".", 1)) for x in os.getenv("IMPUTE_ZERO", "").split(",") if x.strip()}

log = logging.getLogger("silver_pipeline")


def spec(pk, required, order=None, fks=(), **types):
    """types: ts/date/time/num/int/bool -> lista de columnas (el resto es text).
    fks: (columna, tabla_padre, col_padre, 'hard'|'soft'). 'soft' solo se reporta."""
    return dict(pk=pk, required=required, order=order, fks=list(fks), types=types)


# Orden = orden de dependencias (padres primero).
SPECS = {
    "branches": spec(
        ["branch_id"], ["branch_id", "branch_code", "branch_name", "country", "branch_status"],
        bool=["has_atms", "has_teller_windows"], int=["atm_count", "teller_window_count"],
        num=["latitude", "longitude"], date=["branch_opening_date"], time=["opening_time", "closing_time"]),
    "service_agents": spec(
        ["agent_id"], ["agent_id", "employee_code", "agent_status", "hire_date"],
        fks=[("assigned_branch_id", "branches", "branch_id", "soft")],
        date=["hire_date"], num=["avg_csat"], int=["total_monthly_interactions"]),
    "marketing_campaigns": spec(
        ["campaign_id"], ["campaign_id", "campaign_name", "campaign_type", "start_date", "end_date", "campaign_status"],
        date=["start_date", "end_date"], num=["budget", "expected_conversion_rate"]),
    "daily_exchange_rates": spec(
        ["date", "source_currency", "target_currency"],
        ["date", "source_currency", "target_currency", "exchange_rate"],
        date=["date"], num=["exchange_rate", "buy_rate", "sell_rate"]),
    "customers": spec(
        ["customer_id"],
        ["customer_id", "document_number", "document_type", "first_name", "last_name", "date_of_birth",
         "segment", "registration_date", "customer_status", "last_updated"],
        order="last_updated", fks=[("registration_branch_id", "branches", "branch_id", "soft")],
        date=["date_of_birth"], ts=["registration_date", "last_updated"],
        num=["credit_score", "estimated_monthly_income"], bool=["accepts_marketing"]),
    "products": spec(
        ["product_id"],
        ["product_id", "customer_id", "product_type", "product_number", "currency", "current_balance",
         "opening_date", "product_status", "last_updated"],
        order="last_updated",
        fks=[("customer_id", "customers", "customer_id", "hard"), ("opening_branch_id", "branches", "branch_id", "hard")],
        num=["current_balance", "credit_limit", "interest_rate"], date=["opening_date", "expiration_date"],
        bool=["has_linked_app"], int=["days_past_due"], ts=["last_transaction_date", "last_updated"]),
    "call_center_interactions": spec(
        ["interaction_id"],
        ["interaction_id", "interaction_date", "process_date", "customer_id", "agent_id", "interaction_type", "channel"],
        order="process_date",
        fks=[("customer_id", "customers", "customer_id", "hard"), ("agent_id", "service_agents", "agent_id", "hard")],
        ts=["interaction_date"], date=["process_date"], num=["duration_seconds", "wait_time_seconds", "sentiment_score"],
        bool=["was_resolved", "requires_followup", "was_escalated", "has_transcript", "has_recording"]),
    "transactions": spec(
        ["transaction_id"],
        ["transaction_id", "transaction_date", "process_date", "product_id", "customer_id", "transaction_type",
         "amount", "currency", "transaction_status"],
        order="process_date",
        fks=[("customer_id", "customers", "customer_id", "hard"), ("product_id", "products", "product_id", "hard"),
             ("branch_id", "branches", "branch_id", "hard")],
        ts=["transaction_date"], date=["process_date"], num=["amount", "amount_usd", "fraud_score", "latitude", "longitude"],
        bool=["is_fraud"]),
    "complaints": spec(
        ["complaint_id"],
        ["complaint_id", "creation_date", "process_date", "customer_id", "case_type", "category", "status", "priority"],
        order="process_date",
        fks=[("customer_id", "customers", "customer_id", "hard"),
             ("affected_product_id", "products", "product_id", "hard"),
             ("related_branch_id", "branches", "branch_id", "hard"),
             ("assigned_agent_id", "service_agents", "agent_id", "hard"),
             ("origin_interaction_id", "call_center_interactions", "interaction_id", "hard")],
        ts=["creation_date", "assignment_date", "first_response_date", "resolution_date", "closing_date"],
        date=["process_date"], num=["claimed_amount", "resolution_days"], bool=["sla_breached", "is_repeat_complainer"]),
    "call_transcripts": spec(
        ["transcript_id"],
        ["transcript_id", "interaction_id", "process_date", "customer_id", "agent_id", "full_text"],
        order="process_date",
        fks=[("interaction_id", "call_center_interactions", "interaction_id", "hard"),
             ("customer_id", "customers", "customer_id", "hard"), ("agent_id", "service_agents", "agent_id", "hard")],
        date=["process_date"], num=["accent_confidence", "duration_seconds"]),
    "campaign_sends": spec(
        ["send_id"],
        ["send_id", "send_date", "process_date", "campaign_id", "customer_id", "send_channel", "send_status"],
        order="process_date",
        fks=[("campaign_id", "marketing_campaigns", "campaign_id", "hard"), ("customer_id", "customers", "customer_id", "hard")],
        ts=["send_date", "open_date", "click_date", "conversion_date"], date=["process_date"],
        bool=["was_delivered", "was_opened", "was_clicked", "had_conversion"], int=["click_count"],
        num=["conversion_value", "send_cost"]),
    "digital_events": spec(  # customer_id nullable: sesiones anónimas (~24 %)
        ["event_id"], ["event_id", "event_date", "process_date", "session_id", "event_type", "event_category", "channel"],
        order="process_date",
        fks=[("customer_id", "customers", "customer_id", "hard"), ("product_id", "products", "product_id", "hard")],
        ts=["event_date"], date=["process_date"], num=["event_value", "duration_seconds"], bool=["is_mobile"]),
    "satisfaction_surveys": spec(
        ["survey_id"],
        ["survey_id", "survey_date", "process_date", "interaction_id", "customer_id", "agent_id", "survey_type", "main_score"],
        order="process_date",
        fks=[("interaction_id", "call_center_interactions", "interaction_id", "hard"),
             ("customer_id", "customers", "customer_id", "hard"), ("agent_id", "service_agents", "agent_id", "hard")],
        ts=["survey_date"], date=["process_date"], num=["main_score", "response_time_hours", "campaign_response_rate"]),
}

PG_TYPE = {"ts": "timestamp", "date": "date", "time": "time", "num": "numeric"}


def q(ident):
    return '"' + ident.replace('"', '""') + '"'


def norm(alias, col):
    """Texto normalizado: trim y ''/null/nan -> NULL."""
    x = f"btrim({alias}.{q(col)})"
    if "country" in col:  # grafía canónica: 'Mexico' -> 'México'
        x = f"(CASE WHEN lower(translate({x}, 'éÉ', 'eE')) = 'mexico' THEN 'México' ELSE {x} END)"
    return f"(CASE WHEN {x} = '' OR lower({x}) IN ('null','nan') THEN NULL ELSE {x} END)"


def typed(kind, n):
    """Cast seguro: valor inválido -> NULL (nunca lanza error)."""
    if kind == "text":
        return n
    if kind in PG_TYPE:
        return f"(CASE WHEN pg_input_is_valid({n},'{PG_TYPE[kind]}') THEN ({n})::{PG_TYPE[kind]} END)"
    if kind == "int":
        return (f"(CASE WHEN pg_input_is_valid({n},'numeric') THEN "
                f"CASE WHEN ({n})::numeric = trunc(({n})::numeric) THEN ({n})::numeric::bigint END END)")
    if kind == "bool":
        return f"(CASE WHEN lower({n}) IN ('true','false') THEN lower({n})::boolean END)"
    raise ValueError(kind)


def kinds_for(sp, cols):
    kinds = {c: "text" for c in cols}
    for kind, lst in sp["types"].items():
        for c in lst:
            if c not in kinds:
                raise ValueError(f"spec referencia columna inexistente: {c}")
            kinds[c] = kind
    for c in sp["required"] + sp["pk"] + [f[0] for f in sp["fks"]] + ([sp["order"]] if sp["order"] else []):
        if c not in kinds:
            raise ValueError(f"spec referencia columna inexistente: {c}")
    return kinds


def build_stage_sql(t, sp, cols, kinds):
    ncols = ", ".join(f"{norm('b', c)} AS {q(c)}" for c in cols)
    tcols = []
    for c in cols:
        expr = typed(kinds[c], f"n.{q(c)}")
        if (t, c) in IMPUTE_ZERO and kinds[c] in ("num", "int"):
            expr = f"COALESCE({expr}, 0)"
        tcols.append(f"{expr} AS {q(c)}")

    pk_n = ", ".join(f"n.{q(k)}" for k in sp["pk"])
    order = f"{typed(kinds[sp['order']], 'n.' + q(sp['order']))} DESC NULLS LAST, " if sp["order"] else ""
    parts = [f"CASE WHEN row_number() OVER (PARTITION BY {pk_n} ORDER BY {order}n._ingested_at DESC, n._src_ctid DESC) > 1 "
             f"THEN 'duplicate_pk' END"]
    for c in sp["required"]:
        if kinds[c] == "text":
            parts.append(f"CASE WHEN n.{q(c)} IS NULL THEN 'null_{c}' END")
        else:
            parts.append(f"CASE WHEN n.{q(c)} IS NULL THEN 'null_{c}' WHEN {typed(kinds[c], 'n.' + q(c))} IS NULL "
                         f"THEN 'invalid_{c}' END")
    joins = ""
    for i, (c, pt, pc, mode) in enumerate(sp["fks"]):
        if mode != "hard":
            continue
        joins += f" LEFT JOIN {SILVER}.{q(pt)} p{i} ON p{i}.{q(pc)} = n.{q(c)}"
        parts.append(f"CASE WHEN n.{q(c)} IS NOT NULL AND p{i}.{q(pc)} IS NULL THEN 'fk_{c}' END")

    return (f"CREATE UNLOGGED TABLE {SILVER}.{q('_stg_' + t)} AS "
            f"WITH n AS (SELECT b.ctid AS _src_ctid, b._ingested_at, {ncols} FROM {BRONZE}.{q(t)} b) "
            f"SELECT n._src_ctid, n._ingested_at, {', '.join(tcols)}, "
            f"NULLIF(concat_ws(';', {', '.join(parts)}), '') AS _reason "
            f"FROM n{joins}")


def process_table(engine, t, sp):
    with engine.connect() as c:
        cols = [r[0] for r in c.exec_driver_sql(
            "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s "
            "AND column_name<>'_ingested_at' ORDER BY ordinal_position", (BRONZE, t))]
    if not cols:
        raise RuntimeError(f"{BRONZE}.{t} no existe o no tiene columnas")
    kinds = kinds_for(sp, cols)
    stg = f"{SILVER}.{q('_stg_' + t)}"
    col_list = ", ".join(q(c) for c in cols)
    pk_list = ", ".join(q(k) for k in sp["pk"])
    key_expr = "concat_ws('|', " + ", ".join(f"s.{q(k)}::text" for k in sp["pk"]) + ")"

    t0 = time.time()
    with engine.begin() as c:
        c.exec_driver_sql("SET LOCAL statement_timeout = 0")
        c.exec_driver_sql("SET LOCAL work_mem = '256MB'")
        c.exec_driver_sql(f"DROP TABLE IF EXISTS {stg}")
        log.info("[%s] Normalizando, casteando y evaluando reglas...", t)
        c.exec_driver_sql(build_stage_sql(t, sp, cols, kinds))
        c.exec_driver_sql(f"DROP TABLE IF EXISTS {SILVER}.{q(t)}")
        c.exec_driver_sql(f"CREATE TABLE {SILVER}.{q(t)} AS SELECT {col_list}, _ingested_at FROM {stg} WHERE _reason IS NULL")
        c.exec_driver_sql(f"ALTER TABLE {SILVER}.{q(t)} ADD PRIMARY KEY ({pk_list})")
        c.exec_driver_sql(f"DELETE FROM {SILVER}.{QUAR} WHERE source_table = '{t}'")
        c.exec_driver_sql(
            f"INSERT INTO {SILVER}.{QUAR} (source_table, record_key, reasons, payload) "
            f"SELECT '{t}', {key_expr}, s._reason, to_jsonb(b) - '_ingested_at' "
            f"FROM {stg} s JOIN {BRONZE}.{q(t)} b ON b.ctid = s._src_ctid WHERE s._reason IS NOT NULL")
        c.exec_driver_sql(f"DROP TABLE {stg}")

    with engine.connect() as c:
        n_b = c.exec_driver_sql(f"SELECT count(*) FROM {BRONZE}.{q(t)}").scalar()
        n_s = c.exec_driver_sql(f"SELECT count(*) FROM {SILVER}.{q(t)}").scalar()
        reasons = dict(c.exec_driver_sql(
            f"SELECT r, count(*) FROM {SILVER}.{QUAR}, unnest(string_to_array(reasons, ';')) r "
            f"WHERE source_table = '{t}' GROUP BY r ORDER BY 2 DESC").all())
        n_q = c.exec_driver_sql(f"SELECT count(*) FROM {SILVER}.{QUAR} WHERE source_table = '{t}'").scalar()
        # valores no vacíos que no se pudieron castear en columnas anulables (quedan NULL en silver)
        nullable_typed = [x for x in cols if kinds[x] != "text" and x not in sp["required"]]
        cast_nulled = {}
        if nullable_typed:
            sel = ", ".join(
                f"count(*) FILTER (WHERE {norm('b', x)} IS NOT NULL AND {typed(kinds[x], norm('b', x))} IS NULL) AS {q(x)}"
                for x in nullable_typed)
            row = c.exec_driver_sql(f"SELECT {sel} FROM {BRONZE}.{q(t)} b").mappings().first()
            cast_nulled = {k: v for k, v in row.items() if v}
    stats = dict(table=t, bronze=n_b, silver=n_s, quarantined=n_q, reasons=reasons,
                 nullable_cast_failures=cast_nulled, seconds=round(time.time() - t0, 1))
    log.info("[%s] bronze=%d silver=%d cuarentena=%d razones=%s cast_a_NULL=%s (%.1fs)",
             t, n_b, n_s, n_q, reasons or "-", cast_nulled or "-", stats["seconds"])
    return stats


# ---------------------------------------------------------------- Great Expectations
def run_ge(db_url, tables):
    import great_expectations as gx
    import great_expectations.expectations as gxe

    ctx = gx.get_context(mode="ephemeral")
    ds = ctx.data_sources.add_postgres(name="pg", connection_string=db_url)
    out = []  # (tabla, chequeo, severidad, ok, detalle)

    def validate(table, label, asset, expectations, severity="critical"):
        key = f"{table}_{label}".replace(" ", "_")
        bd = asset.add_batch_definition_whole_table(f"bd_{key}")
        suite = ctx.suites.add(gx.ExpectationSuite(name=f"suite_{key}", expectations=expectations))
        vd = ctx.validation_definitions.add(gx.ValidationDefinition(name=f"vd_{key}", data=bd, suite=suite))
        res = vd.run()
        for r in res.results:
            cfg = r.expectation_config
            detail = {k: v for k, v in (r.result or {}).items()
                      if k in ("observed_value", "unexpected_count", "unexpected_percent", "element_count")}
            out.append((table, f"{cfg.type}({label})", severity, bool(r.success), detail))

    for t in tables:
        sp = SPECS[t]
        asset = ds.add_table_asset(name=f"t_{t}", table_name=t, schema_name=SILVER)
        exps = [gxe.ExpectColumnValuesToBeUnique(column=sp["pk"][0]) if len(sp["pk"]) == 1
                else gxe.ExpectCompoundColumnsToBeUnique(column_list=sp["pk"])]
        exps += [gxe.ExpectColumnValuesToNotBeNull(column=c) for c in sp["required"]]
        validate(t, "unicidad_y_not_null", asset, exps)

        # conciliación: filas bronze == silver + cuarentena
        recon = ds.add_query_asset(name=f"q_recon_{t}", query=(
            f"SELECT 1 AS x WHERE (SELECT count(*) FROM {BRONZE}.{q(t)}) <> "
            f"(SELECT count(*) FROM {SILVER}.{q(t)}) + "
            f"(SELECT count(*) FROM {SILVER}.{QUAR} WHERE source_table = '{t}')"))
        validate(t, "conciliacion_filas", recon, [gxe.ExpectTableRowCountToEqual(value=0)])

        for i, (c, pt, pc, mode) in enumerate(sp["fks"]):
            orphans = ds.add_query_asset(name=f"q_fk_{t}_{c}", query=(
                f"SELECT s.{q(c)} FROM {SILVER}.{q(t)} s LEFT JOIN {SILVER}.{q(pt)} p ON p.{q(pc)} = s.{q(c)} "
                f"WHERE s.{q(c)} IS NOT NULL AND p.{q(pc)} IS NULL"))
            validate(t, f"fk_{c}->{pt}", orphans, [gxe.ExpectTableRowCountToEqual(value=0)],
                     severity="critical" if mode == "hard" else "warning")
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler("silver_pipeline.log", encoding="utf-8")])
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        log.error("Falta DATABASE_URL")
        return 1
    wanted = [t for t in os.getenv("TABLES", "").split(",") if t] or list(SPECS)
    tables = [t for t in SPECS if t in wanted]  # respeta el orden de dependencias
    log.info("Inicio bronze=%s -> silver=%s | tablas=%s | impute_zero=%s", BRONZE, SILVER, tables, sorted(IMPUTE_ZERO) or "-")

    engine = create_engine(db_url, pool_pre_ping=True, connect_args={"connect_timeout": 15})
    with engine.begin() as c:
        c.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {SILVER}")
        c.exec_driver_sql(
            f"CREATE TABLE IF NOT EXISTS {SILVER}.{QUAR} (id bigserial PRIMARY KEY, source_table text NOT NULL, "
            f"record_key text, reasons text NOT NULL, payload jsonb NOT NULL, quarantined_at timestamptz NOT NULL DEFAULT now())")
        c.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS silver_quarantine_src_idx ON {SILVER}.{QUAR} (source_table)")

    failed, all_stats = [], []
    for t in tables:
        try:
            all_stats.append(process_table(engine, t, SPECS[t]))
        except Exception:
            log.exception("[%s] FALLÓ la transformación; se omite y se detiene la cascada de hijos", t)
            failed.append(t)
            break  # los hijos dependen del silver del padre

    ge_out = []
    if failed:
        log.error("Transformación incompleta (%s); se omite la validación", failed)
    elif os.getenv("SKIP_GE") == "1":
        log.warning("SKIP_GE=1: se omite Great Expectations")
    else:
        log.info("Ejecutando validaciones de Great Expectations sobre %s...", SILVER)
        ge_out = run_ge(db_url, tables)
        for t_ in tables:
            mine = [x for x in ge_out if x[0] == t_]
            log.info("GE [%s] %d/%d expectations OK", t_, sum(x[3] for x in mine), len(mine))
        for t_, check, sev, ok, detail in ge_out:
            if not ok:
                log.log(logging.ERROR if sev == "critical" else logging.WARNING,
                        "GE [%s] FAIL %s (%s) %s", t_, check, sev, detail)
    crit_fail = [x for x in ge_out if not x[3] and x[2] == "critical"]
    warn_fail = [x for x in ge_out if not x[3] and x[2] == "warning"]

    with open("silver_report.json", "w", encoding="utf-8") as f:
        json.dump(dict(tables=all_stats, ge_failures=[dict(table=a, check=b, severity=c_, detail=e)
                                                       for a, b, c_, ok, e in ge_out if not ok],
                       ge_checks=len(ge_out)), f, indent=2, default=str, ensure_ascii=False)
    log.info("Resumen: %d tablas | GE %d checks, %d críticos fallidos, %d advertencias | reporte: silver_report.json",
             len(all_stats), len(ge_out), len(crit_fail), len(warn_fail))
    return 1 if (failed or crit_fail) else 0


if __name__ == "__main__":
    sys.exit(main())

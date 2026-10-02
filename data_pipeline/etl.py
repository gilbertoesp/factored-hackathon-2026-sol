#!/usr/bin/env python3
"""ETL medallion idempotente: S3 -> bronze -> silver -> gold (PostgreSQL).

Uso:
  python -m data_pipeline.etl [bronze|silver|gold|quality|all] [--force]

Idempotencia (sin --force solo se hace el trabajo que falta):
  bronze  los archivos ya cargados se omiten (bronze._ingestion_log).
  silver  solo se procesan las tablas que aún no existen en el esquema silver.
  gold    solo se construyen las tablas que no existen; siempre corre `checks`.
          Además elimina la columna obsoleta llm_context de gold_customer_360.
  quality pytest de calidad (PK, fechas, monto_usd, fraud_score); falla el ETL si algo no cumple.
--force reconstruye silver/gold completos (silver tarda horas; gold, ~1 h).

Entorno: DATABASE_URL (obligatoria). El resto de variables se documentan en cada módulo.
"""
import argparse
import logging
import os
import sys

from sqlalchemy import create_engine, inspect

from data_pipeline import gold_pipeline, ingest_bronze, silver_pipeline

log = logging.getLogger("etl")
GOLD_TABLES = ["fact_transactions_usd", "gold_customer_360"]


def _existing(engine, schema):
    return set(inspect(engine).get_table_names(schema=schema))


def run_bronze(engine, force):
    return ingest_bronze.main()


def run_silver(engine, force):
    missing = [t for t in silver_pipeline.SPECS if force or t not in _existing(engine, silver_pipeline.SILVER)]
    if not missing:
        log.info("silver: todas las tablas existen; nada que hacer (usa --force para reconstruir)")
        return 0
    os.environ["TABLES"] = ",".join(missing)
    return silver_pipeline.main()


def run_gold(engine, force):
    schema = gold_pipeline.GOLD
    present = _existing(engine, schema)
    if "gold_customer_360" in present and any(
            c["name"] == "llm_context" for c in inspect(engine).get_columns("gold_customer_360", schema=schema)):
        with engine.begin() as c:
            c.exec_driver_sql(f"ALTER TABLE {schema}.gold_customer_360 DROP COLUMN IF EXISTS llm_context")
        log.info("gold: columna obsoleta llm_context eliminada")
    # gold_dispute_features (autoencoder) está obsoleta: se elimina si existe
    if "gold_dispute_features" in present:
        with engine.begin() as c:
            c.exec_driver_sql(f"DROP TABLE IF EXISTS {schema}.gold_dispute_features")
    todo = [t for t in GOLD_TABLES if force or t not in present]
    os.environ["STEPS"] = ",".join(todo) if todo else "__ninguna__"  # vacío = construir todo
    return gold_pipeline.main()


def run_quality(engine, force):
    import pytest
    return int(pytest.main(["-q", os.path.join(os.path.dirname(__file__), "tests", "test_quality.py")]))


STAGES = {"bronze": run_bronze, "silver": run_silver, "gold": run_gold, "quality": run_quality}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", nargs="?", default="all", choices=[*STAGES, "all"])
    ap.add_argument("--force", action="store_true", help="reconstruir silver/gold aunque existan")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s", stream=sys.stdout)
    if not os.getenv("DATABASE_URL"):
        log.error("Falta DATABASE_URL")
        return 1
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True, connect_args={"connect_timeout": 15})
    for name in (STAGES if args.stage == "all" else [args.stage]):
        log.info("=== etapa %s ===", name)
        rc = STAGES[name](engine, args.force)
        if rc:
            log.error("etapa %s falló (rc=%s); se detiene", name, rc)
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())

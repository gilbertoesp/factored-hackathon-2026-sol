#!/usr/bin/env python3
"""Ingesta cruda S3 -> PostgreSQL (esquema bronze).

Descarga los CSV de las tablas `transactions` y `customers` desde S3 y los
carga tal cual (todas las columnas como TEXT, sin limpieza ni filtrado).

Variables de entorno:
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, [AWS_SESSION_TOKEN]
    DATABASE_URL   ej. postgresql+psycopg2://user:pass@host:5432/db
    S3_BUCKET      (opcional) default: factored-datathon-2026-s3-157725502942-us-east-2-an
    S3_PREFIX      (opcional) prefijo donde buscar, default: "data/" (evita data_backup_20260831/)
    AWS_REGION     (opcional) default: us-east-2
"""
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import create_engine, text

BUCKET = os.getenv("S3_BUCKET", "factored-datathon-2026-s3-157725502942-us-east-2-an")
PREFIX = os.getenv("S3_PREFIX", "data/")  # excluye data_backup_20260831/
REGION = os.getenv("AWS_REGION", "us-east-2")
SCHEMA = "bronze"
ALL_TABLES = [
    "transactions", "customers", "branches", "call_center_interactions",
    "call_transcripts", "campaign_sends", "complaints", "daily_exchange_rates",
    "digital_events", "marketing_campaigns", "products", "satisfaction_surveys",
    "service_agents",
]
# TABLES="a,b" limita la corrida a algunas tablas; por defecto las 13
TABLES = [t for t in os.getenv("TABLES", ",".join(ALL_TABLES)).split(",") if t]

log = logging.getLogger("ingest_bronze")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("ingest_bronze.log", encoding="utf-8"),
        ],
    )
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)


def get_s3_client():
    # boto3 toma AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN del entorno
    if not (os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY")):
        raise RuntimeError("Faltan AWS_ACCESS_KEY_ID y/o AWS_SECRET_ACCESS_KEY en el entorno")
    return boto3.client(
        "s3",
        region_name=REGION,
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
        config=Config(retries={"max_attempts": 5, "mode": "standard"}),
    )


def list_table_keys(s3, table: str) -> list[str]:
    """Keys .csv cuyo nombre de archivo o algún segmento de ruta empieza con el nombre de la tabla.

    Cubre layouts como `transactions/dt=2026-01-01/x.csv` o `transactions_2026-01-01.csv`.
    """
    pattern = re.compile(rf"(^|/){re.escape(table)}([/_.=\-]|$)", re.IGNORECASE)
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.lower().endswith(".csv") and pattern.search(key):
                keys.append(key)
    return sorted(keys)


def read_header(path: Path) -> list[str]:
    import csv

    with open(path, newline="", encoding="utf-8-sig") as f:
        return next(csv.reader(f))


def ensure_infra(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {SCHEMA}._ingestion_log (
                s3_key      TEXT PRIMARY KEY,
                table_name  TEXT NOT NULL,
                row_count   BIGINT NOT NULL,
                loaded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
            )"""))


def already_loaded(engine, key: str) -> bool:
    with engine.connect() as conn:
        return conn.execute(
            text(f"SELECT 1 FROM {SCHEMA}._ingestion_log WHERE s3_key = :k"), {"k": key}
        ).first() is not None


def load_file(engine, table: str, key: str, path: Path) -> int:
    """Carga un CSV con COPY. Todo en una transacción: si falla, no queda nada a medias."""
    header = read_header(path)
    quote = engine.dialect.identifier_preparer.quote
    cols_ddl = ", ".join(f"{quote(c)} TEXT" for c in header)
    cols_list = ", ".join(quote(c) for c in header)
    target = f"{SCHEMA}.{quote(table)}"

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(f"CREATE TABLE IF NOT EXISTS {target} ({cols_ddl}, "
                    f"_ingested_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s AND column_name <> '_ingested_at' "
            "ORDER BY ordinal_position", (SCHEMA, table))
        existing = [r[0] for r in cur.fetchall()]
        if existing != header:
            raise ValueError(f"Header de {key} no coincide con {target}: {header} vs {existing}")

        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            cur.copy_expert(
                f"COPY {target} ({cols_list}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL E'\\x01')",
                f,
            )
        rows = cur.rowcount
        cur.execute(
            f"INSERT INTO {SCHEMA}._ingestion_log (s3_key, table_name, row_count) VALUES (%s, %s, %s)",
            (key, table, rows))
        raw.commit()
        return rows
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def main() -> int:
    setup_logging()
    log.info("Inicio ingesta | bucket=%s region=%s prefix=%r", BUCKET, REGION, PREFIX)

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        log.error("Falta la variable de entorno DATABASE_URL")
        return 1

    try:
        s3 = get_s3_client()
        engine = create_engine(db_url, pool_pre_ping=True, connect_args={"connect_timeout": 15})
        ensure_infra(engine)
    except Exception:
        log.exception("Error de inicialización (S3/DB)")
        return 1

    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        for table in TABLES:
            try:
                keys = list_table_keys(s3, table)
            except (ClientError, BotoCoreError):
                log.exception("[%s] Error listando objetos en S3", table)
                failures += 1
                continue

            log.info("[%s] %d archivo(s) CSV encontrados", table, len(keys))
            if not keys:
                log.warning("[%s] Sin archivos; revisa S3_PREFIX o el layout del bucket", table)

            for key in keys:
                if already_loaded(engine, key):
                    log.info("[%s] Omitido (ya cargado): %s", table, key)
                    continue
                local = Path(tmp) / re.sub(r"[^\w.\-]", "_", key)
                try:
                    log.info("[%s] Descargando s3://%s/%s", table, BUCKET, key)
                    s3.download_file(BUCKET, key, str(local))
                    log.info("[%s] Descargado (%d bytes); cargando a %s.%s",
                             table, local.stat().st_size, SCHEMA, table)
                    rows = load_file(engine, table, key, local)
                    log.info("[%s] OK %s -> %d filas", table, key, rows)
                except Exception:
                    failures += 1
                    log.exception("[%s] FALLÓ %s (rollback aplicado, se continúa)", table, key)
                finally:
                    local.unlink(missing_ok=True)

    if failures:
        log.error("Finalizó con %d error(es)", failures)
        return 1
    log.info("Ingesta finalizada correctamente")
    return 0


if __name__ == "__main__":
    sys.exit(main())

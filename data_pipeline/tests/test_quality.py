"""Pruebas de calidad sobre los datos ya cargados (silver/gold). Requieren DATABASE_URL.

Se ejecutan con `pytest data_pipeline/tests/test_quality.py` o como etapa `quality` del ETL.
Son solo lectura (la prueba de disputes inserta dentro de una transacción con rollback).
"""
import os

import pytest
from sqlalchemy import create_engine, exc, inspect

from data_pipeline.silver_pipeline import SPECS

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Falta DATABASE_URL")
SILVER, GOLD = os.getenv("SILVER_SCHEMA", "silver"), os.getenv("GOLD_SCHEMA", "gold")
FX_TOLERANCE = 0.03     # desvío máx. observado vs amount_usd de origen: 2,1 %
MAX_NULL_FRAUD = 0.30   # fraud_score viene nulo en ~20 % de las transacciones (no se imputa)


@pytest.fixture(scope="module")
def conn():
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True, connect_args={"connect_timeout": 15})
    with engine.connect() as c:
        c.exec_driver_sql("SET statement_timeout = 300000")
        yield c
    engine.dispose()


def scalar(conn, sql):
    return conn.exec_driver_sql(sql.replace("%", "%%")).scalar()


# ---- unicidad de llaves primarias
def _pk_cases():
    cases = [(f"{SILVER}.{t}", sp["pk"]) for t, sp in SPECS.items()]
    return cases + [(f"{GOLD}.fact_transactions_usd", ["transaction_id"]),
                    (f"{GOLD}.gold_customer_360", ["customer_id"])]


@pytest.mark.parametrize("table,pk", _pk_cases(), ids=[c[0] for c in _pk_cases()])
def test_pk_unica(conn, table, pk):
    schema, name = table.split(".")
    if name not in inspect(conn).get_table_names(schema=schema):
        pytest.skip(f"{table} aún no existe")
    cols = ", ".join(pk)
    dup = scalar(conn, f"SELECT count(*) - count(DISTINCT ({cols})) FROM {table}")
    nulls = scalar(conn, f"SELECT count(*) FROM {table} WHERE " + " OR ".join(f"{c} IS NULL" for c in pk))
    assert dup == 0 and nulls == 0, f"{table}: {dup} PK duplicadas, {nulls} PK nulas"


# ---- fechas
def test_process_date_dentro_de_un_dia(conn):
    """process_date (bandera de procesamiento) difiere de transaction_date a lo sumo ±1 día."""
    bad = scalar(conn, f"SELECT count(*) FROM {GOLD}.fact_transactions_usd "
                       f"WHERE process_date IS NULL OR abs(process_date - transaction_date::date) > 1")
    assert bad == 0, f"{bad} transacciones con process_date fuera de ±1 día"


def test_fechas_en_rango(conn):
    bad = scalar(conn, f"SELECT count(*) FROM {GOLD}.fact_transactions_usd "
                       f"WHERE transaction_date < '2023-01-01' OR transaction_date > now()")
    assert bad == 0, f"{bad} transacciones con fecha fuera de rango"


# ---- monto_usd y fraud_score
def test_monto_usd_consistente(conn):
    v = f"{GOLD}.transactions_monto_usd"
    assert scalar(conn, f"SELECT count(*) FROM {v} WHERE monto_usd IS NULL OR monto_usd <= 0") == 0
    assert scalar(conn, f"SELECT count(*) FROM {v} WHERE currency = 'USD' AND monto_usd <> amount") == 0
    worst = scalar(conn, f"SELECT COALESCE(max(abs(amount_usd / amount_usd_source - 1)), 0) FROM {v} "
                         f"WHERE currency <> 'USD' AND amount_usd_source > 0")
    assert worst <= FX_TOLERANCE, f"desvío de conversión {worst:.3f} > {FX_TOLERANCE}"


def test_fraud_score_en_rango(conn):
    t = f"{GOLD}.fact_transactions_usd"
    out = scalar(conn, f"SELECT count(*) FROM {t} WHERE fraud_score < 0 OR fraud_score > 100")
    share_null = scalar(conn, f"SELECT avg((fraud_score IS NULL)::int) FROM {t}")
    assert out == 0, f"{out} fraud_score fuera de [0,100]"
    assert share_null <= MAX_NULL_FRAUD, f"{share_null:.1%} de fraud_score nulo"


def test_disputes_rechaza_fraud_score_invalido(conn):
    if "disputes" not in inspect(conn).get_table_names(schema="public"):
        pytest.skip("migración 0002 no aplicada")
    ins = "INSERT INTO public.disputes (customer_id, intent, fraud_score) VALUES ('t', 'ambigua', %s)"
    conn.rollback()  # cierra la transacción autoiniciada por las consultas previas
    tx = conn.begin()
    try:
        conn.exec_driver_sql(ins.replace("%s", "100"))      # válido
        with pytest.raises(exc.IntegrityError):
            with conn.begin_nested():
                conn.exec_driver_sql(ins.replace("%s", "101"))
    finally:
        tx.rollback()

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import etl  # noqa: E402


def tx_crudas(**cambios):
    base = {
        "transaction_id": ["T1", "T2", "T3"],
        "transaction_date": ["2026-06-01 10:00:00", "2026-06-02 10:00:00", "2026-06-03 10:00:00"],
        "process_date": ["2026-06-01", "2026-06-02", "2026-06-03"],
        "product_id": ["P1", "P1", "P2"],
        "customer_id": ["C1", "C1", "C2"],
        "amount": [100.0, 8000.0, 700.0],
        "currency": ["USD", "COP", "ARS"],
        "amount_usd": [None, None, 2.01],
        "merchant_category": ["Food", None, None],
        "transaction_country": ["Mexico", "México", "Colombia"],
        "response_code": [0.0, 14.0, None],
        "is_fraud": [False, True, False],
        "fraud_score": [None, 55.5, 12.0],
        "latitude": [0.0, 0.0, 0.0],
        "longitude": [0.0, 0.0, 0.0],
    }
    base.update(cambios)
    return pd.DataFrame(base)


@pytest.fixture
def fechas():
    registro = pd.Series(pd.to_datetime(["2026-06-02", "2020-01-01"]), index=["C1", "C2"])
    apertura = pd.Series(pd.to_datetime(["2020-01-01", "2026-12-31"]), index=["P1", "P2"])
    return registro, apertura


def test_transactions_monto_usd(fechas):
    df = etl.limpiar_transactions(tx_crudas(), *fechas)
    # USD se copia, COP nulo usa la tasa implícita y el valor de origen se respeta
    assert df["monto_usd"].tolist() == [100.0, 2.0, 2.01]
    assert df["flag_monto_usd_imputado"].tolist() == [True, True, False]


def test_transactions_flags_de_fecha(fechas):
    df = etl.limpiar_transactions(tx_crudas(), *fechas)
    assert df["flag_tx_antes_registro"].tolist() == [True, False, False]
    assert df["flag_tx_antes_apertura"].tolist() == [False, False, True]


def test_transactions_normalizacion_y_tipos(fechas):
    df = etl.limpiar_transactions(tx_crudas(), *fechas)
    assert df["transaction_country"].tolist() == ["México", "México", "Colombia"]
    assert df["response_code"].iloc[:2].tolist() == ["0", "14"]
    assert pd.isna(df["response_code"].iloc[2])
    assert not {"latitude", "longitude", "merchant_category"} & set(df.columns)
    assert str(df["is_fraud"].dtype) == "boolean"


def test_columnas_destino_coinciden_con_la_limpieza(fechas):
    crudo = tx_crudas()
    cols = [c for c, _ in etl.columnas_destino("transactions", crudo.columns)]
    df = etl.limpiar_transactions(crudo, *fechas)
    assert set(cols) == set(df.columns)


def test_products_rompe_colision_de_product_number():
    crudo = pd.DataFrame({
        "product_id": ["P1", "P2", "P3"],
        "customer_id": ["C1", "C2", "C3"],
        "product_number": [111, 111, 222],
        "opening_date": ["2020-01-01"] * 3,
        "expiration_date": [None] * 3,
        "last_transaction_date": [None] * 3,
        "last_updated": ["2020-01-02 00:00:00"] * 3,
        "days_past_due": [None, 0.0, 30.0],
        "has_linked_app": [True, False, True],
    })
    a = etl.limpiar_products(crudo.copy())
    b = etl.limpiar_products(crudo.copy())
    assert a["product_number"].tolist() == ["111", "111-DUP1", "222"]
    assert a["product_number"].tolist() == b["product_number"].tolist()  # determinista
    assert str(a["days_past_due"].dtype) == "Int64"


def test_acentos_nulos_pasan_a_neutral():
    crudo = pd.DataFrame({
        "transcript_id": ["X1", "X2"],
        "process_date": ["2026-06-01", "2026-06-01"],
        "detected_accent": [None, "mexican"],
        "duration_seconds": [None, 120.0],
        "accent_confidence": [0.9, None],
    })
    df = etl.limpiar(crudo, "call_transcripts")
    assert df["detected_accent"].tolist() == ["neutral", "mexican"]


def test_ventana_selecciona_solo_particiones_recientes(tmp_path):
    for dia in ["2026/06/17", "2026/02/17", "2026/02/16"]:
        y, m, d = dia.split("/")
        carpeta = tmp_path / "complaints" / f"year={y}" / f"month={m}" / f"day={d}"
        carpeta.mkdir(parents=True)
        (carpeta / f"complaints_{y}{m}{d}.csv").write_text("complaint_id\n")
    todos = etl.listar_archivos(str(tmp_path), "complaints")
    ventana = etl.listar_archivos(str(tmp_path), "complaints", ventana_dias=120)
    assert len(todos) == 3
    assert len(ventana) == 2  # 17/06 y 17/02 (corte - 120 días); el 16/02 queda fuera
    assert todos == sorted(todos)

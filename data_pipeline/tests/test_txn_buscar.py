import json
import os
import sys
from datetime import date

import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import txn_buscar as tb  # noqa: E402

YO = "CLI-AAAAAAAAAAAA"
OTRO = "CLI-BBBBBBBBBBBB"
SESION = tb.Sesion(customer_id=YO, valida=True)


def fila(n, cliente=YO, fecha=date(2026, 6, 1), monto=100.0, moneda="USD", monto_usd=None,
         comercio="Farmacia Salud", estado="Approved", score=5.0):
    return {"transaction_id": f"TRX-{n:020d}", "customer_id": cliente, "comercio": comercio, "fecha": fecha,
            "amount": monto, "currency": moneda, "transaction_status": estado,
            "monto_usd": monto if monto_usd is None else monto_usd, "fraud_score": score}


def consulta(**cambios):
    base = {"fecha_desde": date(2026, 6, 1), "fecha_hasta": date(2026, 6, 1)}
    base.update(cambios)
    return tb.Consulta(**base)


# ---------------------------------------------------------------- sesión (R01)
def test_sin_sesion_valida_no_responde():
    with pytest.raises(PermissionError):
        tb.construir_resultado(tb.Sesion(customer_id=YO, valida=False), consulta(), [fila(1)])


def test_la_sesion_no_acepta_un_id_mal_formado():
    with pytest.raises(ValidationError):
        tb.Sesion(customer_id="CLI-1' OR '1'='1", valida=True)


# ---------------------------------------------------------------- R09
def test_r09_el_verificador_rechaza_transacciones_de_otro_cliente():
    with pytest.raises(ValidationError, match="otro cliente"):
        tb.construir_resultado(SESION, consulta(), [fila(1), fila(2, cliente=OTRO)])


def test_r09_referencia_ajena_no_trae_candidatas():
    r = tb.ResultadoBusqueda(customer_id=YO, referencia_ajena=True, total_candidatas=0, candidatas=[])
    assert r.hechos_search()["referencesForeignTransaction"] is True
    with pytest.raises(ValidationError):
        tb.ResultadoBusqueda(customer_id=YO, referencia_ajena=True, total_candidatas=1,
                             candidatas=[tb.a_candidata(fila(1))])


def test_el_customer_id_no_se_serializa():
    r = tb.construir_resultado(SESION, consulta(), [fila(1)])
    assert YO not in r.model_dump_json()


# ---------------------------------------------------------------- R10
def test_r10_sin_candidatas():
    r = tb.construir_resultado(SESION, consulta(monto=999.0), [fila(1)])
    assert r.total_candidatas == 0 and r.candidatas == []
    assert r.hechos_search() == {"referencesForeignTransaction": False, "candidates": 0,
                                 "selected": False, "clarificationsAsked": 0}


# ---------------------------------------------------------------- R11
def test_r11_varias_candidatas_devuelve_top_3_y_el_total():
    filas = [fila(n, fecha=date(2026, 6, n)) for n in range(1, 6)]
    r = tb.construir_resultado(SESION, consulta(fecha_desde=date(2026, 6, 1), fecha_hasta=date(2026, 6, 5)), filas)
    assert r.total_candidatas == 5 and len(r.candidatas) == 3
    assert r.hechos_search()["selected"] is False
    # las más cercanas al centro del rango descrito van primero
    assert [c.date.day for c in r.candidatas] == [3, 2, 4]


def test_una_sola_candidata_queda_seleccionada():
    r = tb.construir_resultado(SESION, consulta(), [fila(1)])
    assert r.hechos_search()["selected"] is True


def test_comercio_sin_acentos_ni_mayusculas():
    r = tb.construir_resultado(SESION, consulta(comercio="optica vision"), [fila(1, comercio="Óptica Visión")])
    assert r.total_candidatas == 1


# ---------------------------------------------------------------- moneda
def test_moneda_original_para_el_cliente_y_usd_para_las_reglas():
    r = tb.construir_resultado(SESION, consulta(monto=412000.0, moneda="COP"),
                               [fila(1, monto=412000.0, moneda="COP", monto_usd=103.0)])
    c = r.candidatas[0]
    assert (c.amount, c.currency, c.amountUsd) == (412000.0, "COP", 103.0)


def test_moneda_distinta_no_es_candidata():
    r = tb.construir_resultado(SESION, consulta(monto=100.0, moneda="ARS"), [fila(1, monto=100.0, moneda="USD")])
    assert r.total_candidatas == 0


def test_moneda_fuera_del_catalogo_se_rechaza():
    with pytest.raises(ValidationError):
        consulta(moneda="MXN")  # México opera 100% en USD en este dataset


def test_score_nulo_y_antiguedad():
    c = tb.a_candidata(fila(1, fecha=date(2026, 2, 17), score=None))
    assert c.fraudScore is None and c.ageDays == 120


# ---------------------------------------------------------------- casos reales de D08
RUTA_CASOS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "casos_prueba", "casos_r09_r20.json")


@pytest.fixture(scope="module")
def conn():
    """Base cargada por etl.py; se omite si no hay conexión."""
    psycopg = pytest.importorskip("psycopg")
    from etl import url_base_datos
    try:
        c = psycopg.connect(url_base_datos(), connect_timeout=5)
    except psycopg.OperationalError:
        pytest.skip("sin conexión a la base")
    yield c
    c.close()


@pytest.fixture(scope="module")
def casos():
    if not os.path.exists(RUTA_CASOS):
        pytest.skip("falta casos_prueba/casos_r09_r20.json")
    with open(RUTA_CASOS, encoding="utf-8") as f:
        return json.load(f)["casos"]


def de_regla(casos, regla):
    return [c for c in casos if c["esperado"].get("regla") == regla and c["grupo"] == "decision"]


def sesion_de(caso):
    return tb.Sesion(customer_id=caso["customer_id"], valida=True)


def test_reales_r09_no_distingue_id_ajeno_de_id_inexistente(conn, casos):
    esquema = os.getenv("DB_SCHEMA", "bank")
    for caso in de_regla(casos, "R09"):
        ajeno = tb.buscar_por_id(conn, sesion_de(caso), caso["transaction_ids"][0], esquema)
        inexistente = tb.buscar_por_id(conn, sesion_de(caso), "TRX-" + "0" * 20, esquema)
        assert ajeno.referencia_ajena and ajeno.model_dump() == inexistente.model_dump(), caso["id"]


def test_reales_r10_cero_candidatas(conn, casos):
    for caso in de_regla(casos, "R10"):
        r = tb.buscar(conn, sesion_de(caso), tb.Consulta(**caso["consulta"]), os.getenv("DB_SCHEMA", "bank"))
        assert r.total_candidatas == 0, caso["id"]


def test_reales_r11_ofrece_las_candidatas_esperadas(conn, casos):
    for caso in de_regla(casos, "R11"):
        r = tb.buscar(conn, sesion_de(caso), tb.Consulta(**caso["consulta"]), os.getenv("DB_SCHEMA", "bank"))
        esperadas = set(caso["esperado"]["transacciones_candidatas"])
        assert r.total_candidatas == len(esperadas) > 1, caso["id"]
        assert {c.transactionId for c in r.candidatas} <= esperadas, caso["id"]


def test_reales_r12_por_id_devuelve_la_antiguedad(conn, casos):
    for caso in de_regla(casos, "R12"):
        r = tb.buscar_por_id(conn, sesion_de(caso), caso["transaction_ids"][0], os.getenv("DB_SCHEMA", "bank"))
        assert r.candidatas[0].ageDays > tb.VENTANA_DIAS, caso["id"]

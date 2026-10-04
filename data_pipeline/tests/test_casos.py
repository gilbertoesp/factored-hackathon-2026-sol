import json
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import generar_casos as gc  # noqa: E402

RUTA = os.path.join(gc.DIR_SALIDA, "casos_r09_r20.json")
pytestmark = pytest.mark.skipif(not os.path.exists(RUTA), reason="falta correr generar_casos.py")


@pytest.fixture(scope="module")
def documento():
    with open(RUTA, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def casos(documento):
    return [gc.Caso.model_validate(c) for c in documento["casos"]]


def decidir(h, u):
    """Etapas 3 y 4 de decide() en backend/src/rules/engine.ts, para cargo no reconocido.

    Devuelve (regla, deriva). Es una copia de referencia: si el motor cambia el
    orden de las reglas, este test debe fallar y los casos regenerarse.
    """
    b = h["search"]
    if b["referencesForeignTransaction"]:
        return "R09", False
    if b["candidates"] == 0:
        return "R10", b["clarificationsAsked"] >= u["maxClarifications"]
    if b["candidates"] > 1 and not b["selected"]:
        return "R11", False
    t = h["transaction"]
    if t["ageDays"] > u["searchWindowDays"]:
        return "R12", True
    if t["hasOpenDispute"]:
        return "R13", False
    if t["status"] == "Declined":
        return "R14", False
    if t["status"] == "Reversed":
        return "R16", False
    riesgo_alto = t["fraudScore"] is not None and t["fraudScore"] > u["fraudScoreAutoBlock"]
    if t["status"] == "Pending" and not riesgo_alto:
        return "R15", False
    c = h["customer"]
    if c["recognizesCharge"]:
        return "R17", False
    if riesgo_alto:
        return "R18", True
    if c["unrecognizedCharges"] >= u["unrecognizedChargesForFraud"] or c["cardLostOrStolen"]:
        return "R19", True
    return "R20", True


def test_cubre_r09_a_r20(documento):
    reglas = {f"R{n:02d}" for n in range(9, 21)}
    assert reglas <= set(documento["meta"]["casos_por_regla"])


def test_ids_y_clientes_unicos(casos):
    assert len({c.id for c in casos}) == len(casos)
    assert len({c.customer_id for c in casos}) == len(casos)


def test_regla_esperada_coincide_con_el_motor(documento, casos):
    umbrales = documento["meta"]["umbrales"]
    for c in casos:
        if c.grupo == "busqueda":
            continue
        regla, deriva = decidir(c.hechos, umbrales)
        assert (regla, deriva) == (c.esperado.regla, c.esperado.deriva), c.id
        assert (c.esperado.cola is not None) == deriva, c.id


def test_r18_es_fraude_real_y_prioridad_alta(casos):
    r18 = [c for c in casos if c.esperado.regla == "R18"]
    assert r18 and all(c.es_fraude_real and c.esperado.prioridad == "alta" for c in r18)


def test_consultas_dentro_de_la_ventana(documento, casos):
    corte = date.fromisoformat(documento["meta"]["fecha_referencia"])
    for c in casos:
        if c.grupo == "busqueda":
            assert c.esperado.transaccion_objetivo == c.transaction_ids[0]
            assert 0 <= (corte - c.consulta.fecha_desde).days <= gc.VENTANA_DIAS + gc.TOLERANCIA_DIAS, c.id


def test_sin_datos_personales(documento):
    texto = json.dumps(documento).lower()
    for campo in ["document_number", "first_name", "last_name", "email", "mobile_phone", "address", "@"]:
        assert campo not in texto


def test_clientes_de_prueba_coinciden(casos):
    with open(os.path.join(gc.DIR_SALIDA, "clientes_prueba.txt"), encoding="utf-8") as f:
        clientes = f.read().split()
    assert clientes == sorted({c.customer_id for c in casos})

"""Pruebas del puente al motor TS. Se omiten si no se ejecutó `bash eval/preparar_motor.sh`."""
import json

import pytest

from eval import contra_motor as cm
from motor.contrato import ClassifyResponse

pytestmark = pytest.mark.skipif(not cm.motor_disponible(), reason="motor no montado (bash eval/preparar_motor.sh)")

BASE = {"session": {"valid": True, "otpFailures": 0, "expiredMidFlow": False},
        "message": {"injectionAttempt": False, "asksForHuman": False},
        "intent": {"label": "cargo_no_reconocido", "confidence": 0.9, "clarificationsAsked": 0}}


def test_motor_reglas_de_seguridad():
    ds = cm.ejecutar_motor([
        {**BASE, "session": {"valid": False, "otpFailures": 0, "expiredMidFlow": False}},
        {**BASE, "message": {"injectionAttempt": True, "asksForHuman": False}},
        {**BASE, "intent": {"label": "ambigua", "confidence": 0.9, "clarificationsAsked": 2}}])
    assert [d["ruleId"] for d in ds] == ["R01", "R03", "R06"]
    assert ds[2]["handoff"]["queue"]


def test_error_del_motor_no_tumba_el_lote():
    ds = cm.ejecutar_motor([{"x": 1}, BASE])
    assert ds[0]["kind"] == "error" and ds[1]["kind"] == "awaiting"


def test_d08_coincide_con_el_motor():
    if not cm.CASOS_D08.exists():
        pytest.skip("casos D08 no descargados")
    res = cm.evaluar_d08()
    assert len(res["filas"]) >= 200
    assert [f["id"] for f in res["filas"] if f["difs"]] == []


def test_d08_detecta_discrepancias(tmp_path):
    """Un 100 % no vale si la comparación es vacía: alterar lo esperado debe producir diferencias."""
    if not cm.CASOS_D08.exists():
        pytest.skip("casos D08 no descargados")
    d = json.loads(cm.CASOS_D08.read_text(encoding="utf-8"))
    n = 0
    for c in d["casos"]:
        if "hechos" in c:
            c["esperado"]["regla"] = "R99"
            n += 1
    p = tmp_path / "c.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    assert sum(bool(f["difs"]) for f in cm.evaluar_d08(p)["filas"]) == n


def test_d07_usa_metric_outcome():
    ds = cm.ejecutar_motor([{**BASE, "intent": {"label": "fuera_de_alcance", "confidence": 0.9, "clarificationsAsked": 0}},
                            {**BASE, "intent": {"label": "otro_reclamo", "confidence": 0.9, "clarificationsAsked": 0}}])
    i = cm.indicadores_d07(ds)
    assert i.n == 2 and i.derivadas == 0.5  # R07 contiene; R08 deriva a back office


def test_paso_del_motor_por_idioma():
    ej = [{"text": "a", "intent": "ambigua", "subtype": None, "language": "es-MX"},
          {"text": "b", "intent": "cobro_indebido", "subtype": "duplicado", "language": "pt-BR"},
          {"text": "c", "intent": "fuera_de_alcance", "subtype": "bloqueo_tarjeta", "language": "es-CO"},
          {"text": "d", "intent": "otro_reclamo", "subtype": None, "language": "es-AR"}]
    ok = {"a": ("ambigua", None, 0.9), "b": ("cobro_indebido", "duplicado", 0.9),
          "c": ("fuera_de_alcance", "bloqueo_tarjeta", 0.9), "d": ("otro_reclamo", None, 0.9)}

    def clf(salida):
        return lambda t: ClassifyResponse(intent=salida[t][0], subtype=salida[t][1], confidence=salida[t][2],
                                          language={e["text"]: e["language"] for e in ej}[t])
    assert all(r["ok_paso"] for r in cm.evaluar_idioma_motor(clf(ok), ej))
    # confianza baja en "d": el motor lo trata como ambigua (R05) aunque el clasificador diga otro_reclamo
    malo = dict(ok, d=("otro_reclamo", None, 0.5))
    r = cm.evaluar_idioma_motor(clf(malo), ej)
    assert r[3]["paso"] == "R05" and not r[3]["ok_paso"] and r[0]["ok_paso"]
    assert "| TOTAL | 4 |" in cm.tabla_idioma_motor(r)

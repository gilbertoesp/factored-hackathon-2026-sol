"""Adaptador del baseline de Manuel. Se omite si no se ejecutó `bash eval/preparar_motor.sh`."""
import pytest

from eval import contra_motor, m09_palabras_clave as m

pytestmark = pytest.mark.skipif(not (m.ML / "baseline_keywords.py").exists(), reason="baseline no montado")


def test_reproduce_las_cifras_de_manuel_con_idioma_forzado():
    bk, d = m._cargar(), m.cargar_banking77()
    xs = [e for e in d if e["language"] == "es"]
    pred = [bk.clasificar(e["text"], "es") for e in xs]
    assert len(xs) == 240
    assert round(sum(p == e["intent"] for p, e in zip(pred, xs)) / 240, 3) == 0.571  # ml/resultados/baseline_keywords.json


def test_adaptador_abstencion_y_idioma():
    clf = m.crear_clasificador()
    assert clf("No reconozco este cargo en mi estado de cuenta").intent == "cargo_no_reconocido"
    assert clf("Não reconheço essa cobrança no cartão").language == "pt-BR"
    r = clf("hola buenas")
    assert r.intent == "ambigua" and r.confidence < 0.7


@pytest.mark.skipif(not contra_motor.motor_disponible(), reason="motor no montado")
def test_abstencion_va_a_r05_en_el_motor():
    ej = [dict(text="hola buenas", intent="ambigua", subtype=None, language="es-MX")]
    res = contra_motor.evaluar_idioma_motor(m.crear_clasificador(), ej)
    assert res[0]["paso"] == "R05" and res[0]["ok_paso"]

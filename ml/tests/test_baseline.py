import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import evaluar_baseline as ev  # noqa: E402
from baseline_keywords import PATRONES, clasificar, normalizar  # noqa: E402
from intents import ABSTENCION, CLASE_DE, CLASES, IDIOMAS, MAPEO_BANKING77, PENDIENTES_M01  # noqa: E402


@pytest.mark.parametrize("texto, idioma, clase", [
    ("No reconozco un cobro del martes", "es", "cargo_no_reconocido"),
    ("Me cobraron dos veces la misma compra", "es", "cobro_indebido"),
    ("Mi tarjeta no funciona", "es", "otro_reclamo"),
    ("¿Cómo puedo cambiar mi PIN?", "es", "fuera_de_alcance"),
    ("Não reconheço essa compra", "pt", "cargo_no_reconocido"),
    ("Fui cobrado duas vezes", "pt", "cobro_indebido"),
    ("I was charged twice", "en", "cobro_indebido"),
])
def test_ejemplos_claros(texto, idioma, clase):
    assert clasificar(texto, idioma) == clase


def test_se_abstiene_si_no_hay_ningun_patron():
    assert clasificar("hola, buenas tardes", "es") == ABSTENCION


def test_normaliza_acentos_y_mayusculas():
    assert normalizar("  ¿Comisión   EXTRA? ") == "comision extra?"


def test_empate_respeta_el_orden_de_clases():
    # un patrón de cada una: gana la primera de CLASES
    assert clasificar("no reconozco esta comision", "es") == "cargo_no_reconocido"


def test_patrones_para_cada_idioma_y_clase():
    assert set(PATRONES) == set(IDIOMAS)
    for idioma in IDIOMAS:
        assert set(PATRONES[idioma]) == set(CLASES)


def test_mapeo_sin_intenciones_repetidas_ni_pendientes():
    todas = [i for intents in MAPEO_BANKING77.values() for i in intents]
    assert len(todas) == len(set(todas)) == len(CLASE_DE)
    assert not set(todas) & set(PENDIENTES_M01)


def test_metricas_cuentan_la_abstencion_como_error():
    reales = ["cobro_indebido", "cobro_indebido", "otro_reclamo", "otro_reclamo"]
    predichas = ["cobro_indebido", ABSTENCION, "otro_reclamo", "cobro_indebido"]
    m = ev.metricas(reales, predichas)
    assert m["accuracy"] == 0.5 and m["abstencion"] == 0.25
    assert m["accuracy_respondidas"] == round(2 / 3, 3)
    assert m["por_clase"]["cobro_indebido"] == {"precision": 0.5, "recall": 0.5, "f1": 0.5, "n": 2}


@pytest.mark.skipif(not os.path.exists(ev.SET_PRUEBA), reason="falta sets/banking77_prueba.jsonl")
def test_set_de_prueba_balanceado_y_completo():
    ejemplos = ev.leer_set()
    assert len({e["id"] for e in ejemplos}) == len(ejemplos)
    for clase in CLASES:
        assert sum(e["clase"] == clase for e in ejemplos) == 60
    for e in ejemplos:
        assert CLASE_DE[e["intent_banking77"]] == e["clase"]
        assert all(e[idioma].strip() for idioma in IDIOMAS)

import pytest
from pydantic import ValidationError

from motor.contrato import ClassifyResponse, efectiva


def mk(**kw):
    return ClassifyResponse(**{"intent": "cobro_indebido", "subtype": "duplicado", "confidence": 0.9, "language": "es-CO", **kw})


def test_valido():
    assert mk().subtype == "duplicado"


def test_cobro_indebido_exige_subtipo():
    with pytest.raises(ValidationError):
        mk(subtype=None)


def test_subtipo_ajeno_se_rechaza():
    with pytest.raises(ValidationError):
        mk(subtype="bloqueo_tarjeta")
    assert mk(intent="fuera_de_alcance", subtype="bloqueo_tarjeta").subtype == "bloqueo_tarjeta"


def test_umbral_07():
    assert efectiva(mk(confidence=0.69)).intent == "ambigua"
    assert efectiva(mk(confidence=0.70)).intent == "cobro_indebido"


def test_idioma_invalido():
    with pytest.raises(ValidationError):
        mk(language="en-US")

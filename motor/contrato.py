"""Contrato de entrada del motor de reglas: respuesta del servicio Python `/classify`.

Ver docs/guia_etiquetado.md. Bajo CONFIDENCE_MIN la intención se trata como `ambigua`: nunca se actúa solo.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

CONFIDENCE_MIN = 0.7
Intent = Literal["cargo_no_reconocido", "cobro_indebido", "otro_reclamo", "ambigua", "fuera_de_alcance"]
SUBTYPES = {"cobro_indebido": {"comision", "duplicado", "compra"}, "fuera_de_alcance": {"bloqueo_tarjeta", "otro"}}


class ClassifyResponse(BaseModel):
    intent: Intent
    subtype: Optional[str] = None
    confidence: float = Field(ge=0, le=1)
    language: Literal["es-MX", "es-CO", "es-AR", "pt-BR"]

    @model_validator(mode="after")
    def _subtype_valido(self):
        allowed = SUBTYPES.get(self.intent, set())
        if self.subtype is not None and self.subtype not in allowed:
            raise ValueError(f"subtype {self.subtype!r} no válido para {self.intent}")
        if self.intent == "cobro_indebido" and self.subtype is None:
            raise ValueError("cobro_indebido requiere subtype (comision | duplicado | compra)")
        return self


def efectiva(r: ClassifyResponse) -> ClassifyResponse:
    """Aplica el umbral: confianza < 0,7 -> `ambigua` (sin subtipo)."""
    if r.confidence < CONFIDENCE_MIN and r.intent != "ambigua":
        return r.model_copy(update={"intent": "ambigua", "subtype": None})
    return r

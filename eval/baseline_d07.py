"""D07: línea base del proceso actual (manual) contra la que se compara el motor.

Valores de referencia dados por el negocio (no medidos en este repositorio):
  FCR (resuelto en el primer contacto)  43,6 %
  Tasa de seguimiento                   63 %    (casos que requieren un segundo contacto)
  Tiempo medio de gestión               7,2 min

`medir` calcula indicadores comparables OFFLINE a partir de los resultados del motor de reglas
(backend/src/rules/engine.ts en feat/rules-engine; sus `metricOutcome` y `handoff` se mapean a dos booleanos):
  fcr_proxy         proporción resuelta sin humano ni nuevas preguntas
  seguimiento_proxy proporción que necesita otro contacto (aclaración, datos o derivación)
El tiempo no se puede medir sin tráfico real: queda como None.
"""
from dataclasses import dataclass


BASE_FCR = 0.436
BASE_SEGUIMIENTO = 0.63
BASE_MINUTOS = 7.2


@dataclass
class Indicadores:
    n: int
    fcr_proxy: float
    seguimiento_proxy: float
    derivadas: float
    minutos: float | None = None

    def delta_fcr(self):
        return self.fcr_proxy - BASE_FCR

    def delta_seguimiento(self):
        return self.seguimiento_proxy - BASE_SEGUIMIENTO


def medir(resultados: list[dict]) -> Indicadores:
    """`resultados`: dicts con `resuelta` (sin humano ni preguntas pendientes) y `derivada` (hay handoff)."""
    n = len(resultados)
    if n == 0:
        raise ValueError("sin resultados")
    res = sum(bool(r["resuelta"]) for r in resultados)
    return Indicadores(n=n, fcr_proxy=res / n, seguimiento_proxy=1 - res / n, derivadas=sum(bool(r["derivada"]) for r in resultados) / n)


def tabla(i: Indicadores) -> str:
    return "\n".join([
        "| Indicador | Línea base D07 | Motor (offline) | Δ |", "|---|---|---|---|",
        f"| FCR | {BASE_FCR:.1%} | {i.fcr_proxy:.1%} | {i.delta_fcr():+.1%} |",
        f"| Seguimiento | {BASE_SEGUIMIENTO:.1%} | {i.seguimiento_proxy:.1%} | {i.delta_seguimiento():+.1%} |",
        f"| Tiempo medio | {BASE_MINUTOS} min | n/d (requiere tráfico real) | — |"])

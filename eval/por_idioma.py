"""M09: exactitud del clasificador por idioma. Funciona con cualquier `clasificar(texto) -> dict|ClassifyResponse`."""
import json
from collections import defaultdict
from pathlib import Path

from motor.contrato import efectiva

DATASET = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "textos_etiquetados.jsonl"


def cargar(path=DATASET):
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def evaluar(clasificar, ejemplos):
    """Devuelve lista de resultados por ejemplo: acierta intención, subtipo, idioma, y si hubo error."""
    out = []
    for e in ejemplos:
        try:
            r = efectiva(clasificar(e["text"]))
            ok_i = r.intent == e["intent"]
            ok_s = ok_i and r.subtype == e["subtype"]
            out.append(dict(e, ok_intent=ok_i, ok_exacto=ok_s, ok_idioma=r.language == e["language"], error=None))
        except Exception as ex:  # respuesta inválida del clasificador cuenta como fallo
            out.append(dict(e, ok_intent=False, ok_exacto=False, ok_idioma=False, error=type(ex).__name__))
    return out


def tabla(resultados) -> str:
    por = defaultdict(list)
    for r in resultados:
        por[r["language"]].append(r)
        por["TOTAL"].append(r)
    pct = lambda xs, k: f"{sum(x[k] for x in xs) / len(xs):.0%}"
    filas = ["| Idioma | n | Intención | Intención+subtipo | Idioma detectado | Errores |", "|---|---|---|---|---|---|"]
    for lang in sorted(k for k in por if k != "TOTAL") + ["TOTAL"]:
        xs = por[lang]
        filas.append(f"| {lang} | {len(xs)} | {pct(xs, 'ok_intent')} | {pct(xs, 'ok_exacto')} | {pct(xs, 'ok_idioma')} | {sum(bool(x['error']) for x in xs)} |")
    return "\n".join(filas)

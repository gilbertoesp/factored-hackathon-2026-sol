"""M04: métricas de la línea base por palabras clave sobre el set de prueba.

Reporta, por idioma: accuracy, F1 macro sobre las 4 clases, tasa de abstención
y accuracy sobre lo que sí respondió. La abstención cuenta como error en
accuracy y F1: una línea base que no responde tampoco resolvió el caso.

Uso:
    python evaluar_baseline.py
"""
import json
import os

from baseline_keywords import clasificar
from intents import ABSTENCION, CLASES, IDIOMAS

AQUI = os.path.dirname(os.path.abspath(__file__))
SET_PRUEBA = os.path.join(AQUI, "sets", "banking77_prueba.jsonl")
SALIDA = os.path.join(AQUI, "resultados", "baseline_keywords.json")


def leer_set(ruta=SET_PRUEBA):
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(linea) for linea in f if linea.strip()]


def metricas(reales, predichas):
    """Accuracy, F1 macro y detalle por clase; ABSTENCION nunca es un acierto."""
    n = len(reales)
    por_clase = {}
    for clase in CLASES:
        vp = sum(r == clase and p == clase for r, p in zip(reales, predichas))
        fp = sum(r != clase and p == clase for r, p in zip(reales, predichas))
        fn = sum(r == clase and p != clase for r, p in zip(reales, predichas))
        precision = vp / (vp + fp) if vp + fp else 0.0
        recall = vp / (vp + fn) if vp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        por_clase[clase] = {"precision": round(precision, 3), "recall": round(recall, 3),
                            "f1": round(f1, 3), "n": vp + fn}
    respondidas = [(r, p) for r, p in zip(reales, predichas) if p != ABSTENCION]
    return {
        "n": n,
        "accuracy": round(sum(r == p for r, p in zip(reales, predichas)) / n, 3),
        "f1_macro": round(sum(c["f1"] for c in por_clase.values()) / len(CLASES), 3),
        "abstencion": round(1 - len(respondidas) / n, 3),
        "accuracy_respondidas": round(sum(r == p for r, p in respondidas) / len(respondidas), 3) if respondidas else 0.0,
        "por_clase": por_clase,
        "confusion": {real: {pred: sum(r == real and p == pred for r, p in zip(reales, predichas))
                             for pred in CLASES + [ABSTENCION]} for real in CLASES},
    }


def evaluar(ejemplos):
    reales = [e["clase"] for e in ejemplos]
    return {idioma: metricas(reales, [clasificar(e[idioma], idioma) for e in ejemplos]) for idioma in IDIOMAS}


def main():
    ejemplos = leer_set()
    resultados = evaluar(ejemplos)
    revisados = sum(bool(e.get("revisado")) for e in ejemplos)

    print(f"Set de prueba: {len(ejemplos)} ejemplos de BANKING77 ({revisados} con traducción revisada por una persona)")
    print(f"{'idioma':8s}{'accuracy':>10s}{'F1 macro':>10s}{'abstención':>12s}{'acc. respondidas':>18s}")
    for idioma, m in resultados.items():
        print(f"{idioma:8s}{m['accuracy']:>10.3f}{m['f1_macro']:>10.3f}{m['abstencion']:>12.3f}"
              f"{m['accuracy_respondidas']:>18.3f}")
    for idioma, m in resultados.items():
        print(f"\n[{idioma}] por clase")
        for clase, c in m["por_clase"].items():
            print(f"  {clase:22s} P={c['precision']:.3f} R={c['recall']:.3f} F1={c['f1']:.3f}")

    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"modelo": "baseline_keywords", "set": "sets/banking77_prueba.jsonl",
                   "ejemplos": len(ejemplos), "traducciones_revisadas": revisados,
                   "resultados": resultados}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\nResultados -> {SALIDA}")


if __name__ == "__main__":
    main()

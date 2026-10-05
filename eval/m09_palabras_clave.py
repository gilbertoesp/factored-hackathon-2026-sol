"""M09 con un clasificador real: la línea base por palabras clave de Manuel (`ml/baseline_keywords.py`).

Montaje: `bash eval/preparar_motor.sh`.  Uso: `python -m eval.m09_palabras_clave`

Limitaciones del baseline, que se reflejan en las tablas y no se maquillan:
- 4 clases y abstención: no produce subtipo (la columna "Intención+subtipo" será 0 % para cobro_indebido y
  fuera_de_alcance) ni distingue variantes regionales (es-MX/CO/AR se reportan como "es").
- No da confianza: se usa 0,9 si responde y 0,5 si se abstiene (que el umbral 0,7 vuelve `ambigua`, R05).
- Detecta el idioma sumando los patrones de cada idioma (es, pt, en); empate -> es.
"""
import importlib.util
import json
import sys
from pathlib import Path

from eval import contra_motor, por_idioma
from motor.contrato import ClassifyResponse

ML = contra_motor.RAIZ / ".motor" / "ml"


def _cargar():
    if not (ML / "baseline_keywords.py").exists():
        raise RuntimeError("falta el baseline: ejecuta `bash eval/preparar_motor.sh`")
    sys.path.insert(0, str(ML))  # baseline_keywords hace `from intents import ...`
    spec = importlib.util.spec_from_file_location("baseline_keywords", ML / "baseline_keywords.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def crear_clasificador():
    bk = _cargar()
    idiomas = list(bk.PATRONES)

    def clasificar(texto):
        tot = {i: sum(bk.puntajes(texto, i).values()) for i in idiomas}
        idioma = max(idiomas, key=lambda i: (tot[i], i == "es"))
        clase = bk.clasificar(texto, idioma)
        # model_construct: el contrato exige subtipo en cobro_indebido y el baseline no lo produce.
        return ClassifyResponse.model_construct(
            intent=clase, subtype=None, confidence=0.5 if clase == bk.ABSTENCION else 0.9,
            language={"es": "es-MX", "pt": "pt-BR", "en": "en"}[idioma])
    return clasificar


def cargar_banking77():
    """240 consultas x 3 idiomas; la etiqueta es la clase (sin subtipo). Traducción automática, sin revisar."""
    filas = [json.loads(l) for l in (ML / "banking77_prueba.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    return [dict(text=f[i], intent=f["clase"], subtype=None, language=i, source="banking77") for f in filas for i in ("es", "pt", "en")]


def tabla_con_abstencion(res, motor=True) -> str:
    from collections import defaultdict
    por = defaultdict(list)
    for r in res:
        por[r["language"]].append(r)
        por["TOTAL"].append(r)
    pct = lambda xs, k: f"{sum(bool(x[k]) for x in xs) / len(xs):.0%}"
    filas = ["| Idioma | n | Intención correcta | Paso correcto del motor |", "|---|---|---|---|"]
    for lang in sorted(k for k in por if k != "TOTAL") + ["TOTAL"]:
        xs = por[lang]
        filas.append(f"| {lang} | {len(xs)} | {pct(xs, 'ok_intent')} | {pct(xs, 'ok_paso')} |")
    return "\n".join(filas)


def main():
    clf = crear_clasificador()
    print("## M09 sintético (32 textos, variantes regionales)\n")
    print(contra_motor.tabla_idioma_motor(contra_motor.evaluar_idioma_motor(clf, por_idioma.cargar())))
    print("\n## M09 Banking77 (240 consultas x es/pt/en; traducción automática sin revisar)\n")
    res = contra_motor.evaluar_idioma_motor(clf, cargar_banking77())
    print(tabla_con_abstencion(res))
    print("\nAbstenciones (R05) por idioma:",
          {l: sum(r["paso"] == "R05" for r in res if r["language"] == l) for l in ("es", "pt", "en")})


if __name__ == "__main__":
    main()

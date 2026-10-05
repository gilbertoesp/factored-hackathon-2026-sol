"""Evaluación contra el motor de reglas REAL (R01-R29, TypeScript de `feat/rules-engine`).

Montaje: `bash eval/preparar_motor.sh` (deja el motor y los casos D08 de Manuel en .motor/).
Uso:     python -m eval.contra_motor            # D08 (R09-R20) + D07 proxy + paso del motor por idioma (oráculo)

- D08: los `hechos` de cada caso (forma de `Facts`) se pasan a `decide` y se comparan con `esperado`.
- D07: indicadores proxy a partir de `metricOutcome` y del handoff del motor. OJO: los casos D08 están balanceados
  por regla (~20 por regla, todos `cargo_no_reconocido`), no siguen la distribución real de reclamos, así que el
  resultado NO es comparable con la línea base (FCR 43,6 %).
- M09: el clasificador alimenta el primer paso del motor (R05/R07/R08 o pedir búsqueda) y se mide por idioma.
"""
import json
import os
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from eval import baseline_d07, por_idioma

RAIZ = Path(__file__).resolve().parent.parent
ENGINE_DIR = Path(os.getenv("ENGINE_DIR", RAIZ / ".motor" / "engine" / "rules"))
CASOS_D08 = Path(os.getenv("CASOS_D08", RAIZ / ".motor" / "casos_r09_r20.json"))
RUNNER = Path(__file__).resolve().parent / "engine_runner.mts"


def tsx_bin():
    local = ENGINE_DIR.parent / "node_modules" / ".bin" / "tsx"
    return str(local) if local.exists() else shutil.which("tsx")


def motor_disponible() -> bool:
    return (ENGINE_DIR / "engine.ts").exists() and tsx_bin() is not None


def ejecutar_motor(facts: list[dict]) -> list[dict]:
    """Llama a `decide` del motor TS por cada `Facts`. Un error del motor devuelve {"kind": "error"}."""
    if not motor_disponible():
        raise RuntimeError("motor no disponible: ejecuta `bash eval/preparar_motor.sh`")
    p = subprocess.run([tsx_bin(), str(RUNNER)], input=json.dumps(facts), capture_output=True, text=True,
                       env={**os.environ, "ENGINE_DIR": str(ENGINE_DIR)}, timeout=120)
    if p.returncode != 0:
        raise RuntimeError(f"fallo del motor: {p.stderr[-500:]}")
    return json.loads(p.stdout)


def resumen(d: dict) -> dict:
    """Decisión del motor en los términos de `esperado` de D08."""
    h = d.get("handoff")
    return {"regla": d.get("ruleId"), "deriva": h is not None, "cola": h["queue"] if h else None,
            "prioridad": h["priority"] if h else None, "espera": d.get("awaiting")}


def evaluar_d08(path=CASOS_D08) -> dict:
    casos = [c for c in json.loads(Path(path).read_text(encoding="utf-8"))["casos"] if "hechos" in c]
    decisiones = ejecutar_motor([c["hechos"] for c in casos])
    filas = []
    for c, d in zip(casos, decisiones):
        got, exp = resumen(d), c["esperado"]
        difs = {k: (exp[k], got[k]) for k in ("regla", "deriva", "cola", "prioridad") if k in exp and exp[k] != got[k]}
        filas.append(dict(id=c["id"], grupo=c["grupo"], regla=exp["regla"], decision=d, difs=difs))
    return dict(filas=filas)


def tabla_d08(res) -> str:
    por = defaultdict(lambda: [0, 0])
    for f in res["filas"]:
        por[f["regla"]][0] += 1
        por[f["regla"]][1] += not f["difs"]
    filas = ["| Regla esperada | Casos | Coinciden | % |", "|---|---|---|---|"]
    for r in sorted(por):
        n, ok = por[r]
        filas.append(f"| {r} | {n} | {ok} | {ok / n:.0%} |")
    n, ok = sum(v[0] for v in por.values()), sum(v[1] for v in por.values())
    filas.append(f"| **Total** | {n} | {ok} | {ok / n:.0%} |")
    return "\n".join(filas)


def indicadores_d07(decisiones: list[dict]) -> baseline_d07.Indicadores:
    """Resuelta = la matriz la cuenta como resolución (`metricOutcome` 'Resolución…'); derivada = hay handoff."""
    return baseline_d07.medir([dict(resuelta=str(d.get("metricOutcome", "")).startswith("Resolución"),
                                    derivada=d.get("handoff") is not None) for d in decisiones])


# ---- M09: primer paso del motor por idioma ------------------------------------------------------------------
PASO_ESPERADO = {"ambigua": "R05", "fuera_de_alcance": "R07", "otro_reclamo": "R08",
                 "cargo_no_reconocido": "search", "cobro_indebido": "search"}


def facts_primer_paso(r) -> dict:
    intent = {"label": r.intent, "confidence": r.confidence, "clarificationsAsked": 0}
    if r.intent == "fuera_de_alcance" and r.subtype:
        intent["outOfScopeTopic"] = r.subtype
    return {"session": {"valid": True, "otpFailures": 0, "expiredMidFlow": False},
            "message": {"injectionAttempt": False, "asksForHuman": False}, "intent": intent}


def evaluar_idioma_motor(clasificar, ejemplos):
    """Como `por_idioma.evaluar`, más `paso` (lo que hace el motor con la salida del clasificador) y `ok_paso`."""
    res = por_idioma.evaluar(clasificar, ejemplos)
    idx, facts = [], []
    for i, (e, r) in enumerate(zip(ejemplos, res)):
        if r["error"] is None:
            idx.append(i)
            facts.append(facts_primer_paso(clasificar(e["text"])))
    for i, d in zip(idx, ejecutar_motor(facts) if facts else []):
        res[i]["paso"] = d.get("ruleId") or d.get("awaiting")
    for e, r in zip(ejemplos, res):
        r["paso"] = r.get("paso")
        r["ok_paso"] = r["paso"] == PASO_ESPERADO[e["intent"]]
    return res


def tabla_idioma_motor(res) -> str:
    por = defaultdict(list)
    for r in res:
        por[r["language"]].append(r)
        por["TOTAL"].append(r)
    pct = lambda xs, k: f"{sum(bool(x[k]) for x in xs) / len(xs):.0%}"
    filas = ["| Idioma | n | Intención | Intención+subtipo | Paso correcto del motor |", "|---|---|---|---|---|"]
    for lang in sorted(k for k in por if k != "TOTAL") + ["TOTAL"]:
        xs = por[lang]
        filas.append(f"| {lang} | {len(xs)} | {pct(xs, 'ok_intent')} | {pct(xs, 'ok_exacto')} | {pct(xs, 'ok_paso')} |")
    return "\n".join(filas)


def main():
    res = evaluar_d08()
    print(f"## D08 contra el motor ({(RAIZ / '.motor' / 'VERSIONES').read_text().strip() if (RAIZ / '.motor' / 'VERSIONES').exists() else ''})\n")
    print(tabla_d08(res))
    malos = [f for f in res["filas"] if f["difs"]]
    for f in malos[:15]:
        print(f"  ✗ {f['id']}: {f['difs']}")
    if len(malos) > 15:
        print(f"  … y {len(malos) - 15} más")
    print("\n## D07 (proxy, NO comparable: casos balanceados por regla)\n")
    print(baseline_d07.tabla(indicadores_d07([f["decision"] for f in res["filas"]])))
    print("\nResultados por regla del motor:", dict(Counter(f["decision"].get("ruleId") for f in res["filas"])))
    ej = por_idioma.cargar()
    por_texto = {e["text"]: e for e in ej}
    from motor.contrato import ClassifyResponse
    oraculo = lambda t: ClassifyResponse(confidence=0.9, **{k: por_texto[t][k] for k in ("intent", "subtype", "language")})
    print("\n## M09 con clasificador oráculo (verifica el flujo; sustituir por /classify o el zero-shot)\n")
    print(tabla_idioma_motor(evaluar_idioma_motor(oraculo, ej)))


if __name__ == "__main__":
    main()

"""M03: muestra determinista del set de prueba de BANKING77 para nuestras clases.

Descarga el split de prueba original (inglés), se queda con las intenciones de
MAPEO_BANKING77 y toma EJEMPLOS_POR_CLASE por clase, repartidos entre sus
intenciones. La selección ordena por md5 del texto, así que siempre da lo mismo.

Las traducciones a español y portugués viven en sets/banking77_prueba.jsonl. Este
script no traduce: escribe la muestra en inglés (sets/banking77_muestra_en.jsonl)
y verifica que el archivo traducido corresponda exactamente a esa muestra.

Uso:
    python preparar_banking77.py
"""
import csv
import hashlib
import io
import json
import os
import sys
import urllib.request

from intents import MAPEO_BANKING77

URL = "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/test.csv"
AQUI = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(AQUI, "data", "banking77_test.csv")  # ignorado por git
MUESTRA = os.path.join(AQUI, "sets", "banking77_muestra_en.jsonl")
TRADUCIDO = os.path.join(AQUI, "sets", "banking77_prueba.jsonl")
EJEMPLOS_POR_CLASE = 60


def md5(texto):
    return hashlib.md5(texto.encode("utf-8")).hexdigest()


def descargar():
    if not os.path.exists(CACHE):
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with urllib.request.urlopen(URL, timeout=60) as r, open(CACHE, "wb") as f:
            f.write(r.read())
    with open(CACHE, encoding="utf-8") as f:
        return list(csv.DictReader(io.StringIO(f.read())))


def muestrear(filas):
    muestra = []
    for clase, intents in MAPEO_BANKING77.items():
        por_intent = {i: sorted({f["text"].strip() for f in filas if f["category"] == i}, key=md5) for i in intents}
        elegidos, ronda = [], 0
        while len(elegidos) < EJEMPLOS_POR_CLASE:  # una por intención en cada ronda
            for intent in intents:
                if ronda < len(por_intent[intent]) and len(elegidos) < EJEMPLOS_POR_CLASE:
                    elegidos.append((intent, por_intent[intent][ronda]))
            ronda += 1
        for intent, texto in elegidos:
            muestra.append({"id": f"B77-{md5(texto)[:10]}", "clase": clase, "intent_banking77": intent, "en": texto})
    return sorted(muestra, key=lambda m: m["id"])


def leer_jsonl(ruta):
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(linea) for linea in f if linea.strip()]


def main():
    muestra = muestrear(descargar())
    os.makedirs(os.path.dirname(MUESTRA), exist_ok=True)
    with open(MUESTRA, "w", encoding="utf-8", newline="\n") as f:
        for m in muestra:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    print(f"{len(muestra)} ejemplos en inglés -> {MUESTRA}")

    if not os.path.exists(TRADUCIDO):
        sys.exit("Falta sets/banking77_prueba.jsonl con las traducciones.")
    traducido = {t["id"]: t for t in leer_jsonl(TRADUCIDO)}
    faltan = [m["id"] for m in muestra if m["id"] not in traducido]
    sobran = sorted(set(traducido) - {m["id"] for m in muestra})
    distintos = [m["id"] for m in muestra if m["id"] in traducido and (
        traducido[m["id"]]["en"] != m["en"] or traducido[m["id"]]["clase"] != m["clase"])]
    if faltan or sobran or distintos:
        sys.exit(f"El set traducido no coincide con la muestra: faltan {len(faltan)}, "
                 f"sobran {len(sobran)}, distintos {len(distintos)}.")
    print(f"El set traducido coincide con la muestra ({len(traducido)} ejemplos).")


if __name__ == "__main__":
    main()

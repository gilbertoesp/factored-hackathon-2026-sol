"""Exporta docs/matriz_decision_es.xlsx a backend/src/rules/rules.json.

El Excel es la fuente de verdad de la política (lo edita el equipo); el motor
de reglas lee solo el JSON. Correr después de cada cambio en la matriz:

    python backend/scripts/export_rules.py

Los umbrales se leen como valores crudos de la hoja Umbrales. Los textos de la
hoja Matriz se leen con el valor calculado por Excel (data_only), porque
algunas condiciones son fórmulas que citan los umbrales. Si el archivo se
guardó sin calcular (por ejemplo, desde openpyxl) el script falla en vez de
exportar fórmulas sin resolver.

Requiere: openpyxl.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "matriz_decision_es.xlsx"
OUT = ROOT / "backend" / "src" / "rules" / "rules.json"

# Etiqueta en la hoja Umbrales -> clave en el JSON. Una etiqueta nueva o
# renombrada rompe la exportación a propósito: el motor no debe correr con un
# umbral que nadie mapeó.
THRESHOLD_KEYS = {
    "fraud_score: bloqueo automático (estrictamente mayor que)": "fraudScoreAutoBlock",
    "Cargos no reconocidos para sospechar fraude con score bajo": "unrecognizedChargesForFraud",
    "Confianza mínima del clasificador": "minIntentConfidence",
    "Máximo de aclaraciones": "maxClarifications",
    "Ventana de búsqueda de transacciones": "searchWindowDays",
    "Tolerancia de fecha al buscar": "dateToleranceDays",
    "Límite de reversión automática (cobro indebido)": "autoReversalLimitUsd",
    "Periodo para 'primera ocurrencia'": "firstOccurrenceMonths",
    "Ventana de cargo duplicado": "duplicateWindowMinutes",
    "Intentos OTP antes de bloquear sesión": "otpMaxAttempts",
    "Reintentos por herramienta": "toolRetries",
}

# Columna de la hoja Matriz -> clave en el JSON.
RULE_COLUMNS = {
    "ID": "id",
    "Etapa": "stage",
    "Intención": "intent",
    "Condición (legible)": "condition",
    "Acción del sistema": "action",
    "Herramientas (en orden)": "tools",
    "Verificación posterior": "verification",
    "Mensaje al cliente (resumen)": "message",
    "¿Deriva a humano?": "handoff",
    "Destino / cola": "queue",
    "Resultado para métricas": "metricOutcome",
    "Origen del dato de prueba": "testDataOrigin",
    "Casos de prueba mínimos": "testCases",
}



def header_row(ws, first: str) -> int:
    """Fila cuyo primer valor es `first`; tolera filas de título agregadas."""
    for row in ws.iter_rows(min_col=1, max_col=1):
        if row[0].value == first:
            return row[0].row
    sys.exit(f"No encuentro el encabezado {first!r} en la hoja {ws.title}")


def clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text in ("", "-") else text


def read_thresholds(wb) -> dict[str, float]:
    ws = wb["Umbrales"]
    out: dict[str, float] = {}
    start = header_row(ws, "Parámetro") + 1
    for label, value, *_ in ws.iter_rows(min_row=start, values_only=True):
        if label is None:
            continue
        key = THRESHOLD_KEYS.get(str(label).strip())
        if key is None:
            sys.exit(f"Umbral sin mapear en THRESHOLD_KEYS: {label!r}")
        if not isinstance(value, (int, float)):
            sys.exit(f"Umbral {label!r} no es numérico: {value!r}")
        out[key] = value
    missing = set(THRESHOLD_KEYS.values()) - set(out)
    if missing:
        sys.exit(f"Faltan umbrales en la hoja: {sorted(missing)}")
    return out


def read_rules(wb) -> list[dict]:
    ws = wb["Matriz"]
    top = header_row(ws, "ID")
    headers = [c.value for c in ws[top]]
    index = {}
    for name, key in RULE_COLUMNS.items():
        if name not in headers:
            sys.exit(f"Columna {name!r} no está en la hoja Matriz")
        index[key] = headers.index(name)

    rules = []
    for row in ws.iter_rows(min_row=top + 1, values_only=True):
        rule_id = clean(row[index["id"]])
        if not rule_id or not rule_id.startswith("R"):
            continue
        rule = {key: clean(row[i]) for key, i in index.items()}
        for key, text in rule.items():
            if text and text.startswith("="):
                sys.exit(
                    f"{rule_id}.{key} es una fórmula sin valor calculado. "
                    "Abre el Excel, guárdalo y vuelve a exportar."
                )
        rule["tools"] = [t.strip() for t in (rule["tools"] or "").split(";") if t.strip()]
        rules.append(rule)

    # Rows follow the stage order, so a rule added later (R29 in stage 4) sits
    # between older ids. What must hold is that ids are unique and contiguous.
    ids = [r["id"] for r in rules]
    expected = [f"R{n:02d}" for n in range(1, len(ids) + 1)]
    if sorted(ids) != expected:
        sys.exit(f"IDs de regla repetidos o con huecos: {ids}")
    return rules


def main() -> None:
    raw = load_workbook(SRC)  # valores crudos: umbrales
    calc = load_workbook(SRC, data_only=True)  # textos ya calculados
    payload = {
        "source": SRC.relative_to(ROOT).as_posix(),
        "note": "Generado por backend/scripts/export_rules.py. No editar a mano.",
        "thresholds": read_thresholds(raw),
        "rules": read_rules(calc),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(payload['rules'])} reglas y {len(payload['thresholds'])} umbrales -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

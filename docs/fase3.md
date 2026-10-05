# Fase 3: evaluación contra el motor de reglas

**Fuente de verdad de las reglas:** `backend/src/rules/engine.ts` y `rules.json` en la rama `feat/rules-engine`
(matriz `docs/matriz_decision_es.xlsx`). Este repositorio no mantiene un segundo `decide`: un arnés Python propio
(E01) se escribió con supuestos y se retiró al comprobar que contradecía la matriz (R20-R23, R29, topes de 25 USD,
fraude 30, duplicado en 10 min).

Lo que sí aporta este lado, para alimentar los `Facts` del motor:
- `motor/contrato.py`: salida de `/classify` y umbral 0,7 (coincide con `minIntentConfidence`).
- `motor/txn_buscar.py`: búsqueda acotada al cliente. Existe otra versión en la rama de Manuel (D10): hay que elegir una.
- `motor/subtipo_cobro.py`: `kind` (comisión/compra) y duplicado en <= 10 min (`duplicateGapMinutes`, R23).

## Evaluación (`eval/`)
- `baseline_d07.py` (D07): referencia del negocio (FCR 43,6 %, seguimiento 63 %, 7,2 min; no medidos aquí). `medir`
  recibe resultados ya mapeados desde el motor. **Pendiente:** conectarlo al motor TS con los casos D08 de Manuel
  (`data_pipeline/casos_prueba/casos_r09_r20.json`). Sin tráfico real no hay tiempo medio.
- `llm_zero_shot.py` (M06): `python -m eval.llm_zero_shot` (requiere `pip install anthropic` y `ANTHROPIC_API_KEY`;
  modelo `claude-haiku-4-5-20251001`, `ZERO_SHOT_MODEL` lo cambia). **Pendiente: correrlo.**
- `por_idioma.py` (M09): acepta cualquier clasificador. Dataset provisional `tests/fixtures/textos_etiquetados.jsonl`
  (32 textos sintéticos, 8 por idioma): sirve para el flujo, no para conclusiones.
- B08: ver `docs/adversarial_b08.md`.

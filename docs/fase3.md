# Fase 3: evaluación contra el motor de reglas

**Fuente de verdad de las reglas:** `backend/src/rules/engine.ts` y `rules.json` en la rama `feat/rules-engine`
(matriz `docs/matriz_decision_es.xlsx`). Este repositorio no mantiene un segundo `decide`: un arnés Python propio
(E01) se escribió con supuestos y se retiró al comprobar que contradecía la matriz (R20-R23, R29, topes de 25 USD,
fraude 30, duplicado en 10 min).

Lo que sí aporta este lado, para alimentar los `Facts` del motor:
- `motor/contrato.py`: salida de `/classify` y umbral 0,7 (coincide con `minIntentConfidence`).
- `motor/txn_buscar.py`: búsqueda acotada al cliente. Existe otra versión en la rama de Manuel (D10): hay que elegir una.
- `motor/subtipo_cobro.py`: `kind` (comisión/compra) y duplicado en <= 10 min (`duplicateGapMinutes`, R23).

## Evaluación contra el motor real (`eval/`)
Montaje: `bash eval/preparar_motor.sh` deja en `.motor/` (ignorado por git) el motor de `origin/feat/rules-engine` y los
casos D08 de `origin/feat/hackathon-data-pipeline_v1`, sin mezclar historias. Necesita Node y red para `npm i zod tsx`.
Ejecución: `python -m eval.contra_motor`. `eval/engine_runner.mts` es el puente: lee `Facts` y devuelve las
decisiones de `decide` del motor TS. Las pruebas (`tests/test_contra_motor.py`) se omiten si el motor no está montado.

- **D08 (rama de Manuel):** 265 casos con `hechos`, R09-R20, todos `cargo_no_reconocido`. El motor coincide en
  265/265 en regla, derivación, cola y prioridad (motor `6a89c5d`, casos `67b020f`). Los casos salieron de la misma
  matriz, así que esto confirma la integración y la paridad con lo que Manuel esperaba, no la calidad del negocio.
  Los 60 casos de `busqueda` son el recall de `txn.buscar` y necesitan la base de datos: no se evaluaron aquí.
- **D07:** `baseline_d07.py` (referencia FCR 43,6 %, seguimiento 63 %, 7,2 min; no medidos aquí). Con D08 sale
  FCR proxy 50,9 %, pero **no es comparable**: los casos están balanceados por regla (~20 por regla) y solo cubren
  cargos no reconocidos, no la mezcla real de reclamos. La comparación válida necesita la distribución real de
  intenciones y el tiempo medio solo existe con tráfico real.
- **M09:** `eval/contra_motor.py` pasa la salida del clasificador al primer paso del motor (R05/R07/R08 o pedir
  búsqueda) y mide por idioma. Hoy corre con un clasificador oráculo (verifica el flujo); falta enchufar `/classify`
  o el zero-shot. Con confianza < 0,7 el motor responde R05 aunque el clasificador diga otra cosa (probado).
- **M09 con clasificador real (`python -m eval.m09_palabras_clave`):** usa la línea base por palabras clave de Manuel
  (`ml/baseline_keywords.py`, M04) como clasificador y el motor real para el primer paso. Sobre Banking77 (240 consultas
  x es/pt/en, traducción automática sin revisar) acierta la intención en 59 % (es 60, pt 58, en 60 %) y se abstiene
  (R05) en ~35 % de los casos; con el idioma forzado reproduce las cifras de Manuel (es 57,1 %, abstención 38,3 %).
  Sobre los 32 textos sintéticos regionales: 59 % de intención, sin diferencia clara entre variantes (n = 8 por
  idioma). No produce subtipo ni distingue es-MX/CO/AR, y su "confianza" es fija (0,9 o 0,5). Es un piso de
  comparación, no el clasificador final: el `/classify` real y el zero-shot (M06) siguen pendientes.
- **M06 (`llm_zero_shot.py`):** `python -m eval.llm_zero_shot` (requiere `pip install anthropic` y `ANTHROPIC_API_KEY`;
  modelo `claude-haiku-4-5-20251001`). **Pendiente: correrlo.**
- `por_idioma.py` y el dataset `tests/fixtures/textos_etiquetados.jsonl` (32 textos sintéticos): sirven para el flujo,
  no para conclusiones.
- B08: ver `docs/adversarial_b08.md`.

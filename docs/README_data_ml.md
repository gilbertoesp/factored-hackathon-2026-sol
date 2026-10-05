# Pipeline de Datos, Capa Medallion y Motor de Búsqueda de Transacciones
**Data & ML Engineering Architecture**

Transforma un conjunto masivo de datos transaccionales, interacciones y llamadas bancarias heterogéneas en un pipeline de datos robusto, versionado, idempotente y reproducible bajo arquitectura Medallion (Bronze, Silver, Gold) sobre PostgreSQL RDS, asegurando además la resolución segura y precisa de reclamos mediante un algoritmo de recuperación transaccional de alto rendimiento.

---

## 1. Arquitectura del Pipeline de Datos (Medallion Layer)

El pipeline de datos fue refactorizado y migrado desde un entorno exploratorio inicial hacia un script ejecutable e idempotente escrito en Python modular (`data_pipeline/etl.py`), ejecutable de forma aislada mediante Docker Compose (`docker compose --profile medallion run --rm medallion`).

- **Capa Bronze (`ingest_bronze.py`):** Ingesta directa de 13 tablas en PostgreSQL RDS desde archivos Parquet/CSV sin alteración hacia tablas espejo.
- **Capa Silver (`silver_pipeline.py`):** Limpieza, tipado estricto, normalización y desduplicación sobre 10 tablas centrales.
- **Capa Gold (`gold_pipeline` / Migración SQL):** Tablas y vistas analíticas optimizadas para el motor de decisión y la analítica de fraude.

### Detalle Operativo por Capas

| Capa | Tablas / Objetos | Operaciones Clave |
| :--- | :--- | :--- |
| **Bronze** | 13 Tablas | Carga raw punto a punto desde Parquet/CSV sin transformaciones estructurales. |
| **Silver** | 10 Tablas | Limpieza de formatos de fecha, casting seguro a tipos nativos PostgreSQL, manejo explícito de nulos sin pérdida de registros. |
| **Gold** | `gold.fact_transactions_usd`, `public.disputes`, `handoff_tickets` | Recálculo de `amount_usd` mediante tasa diaria (`daily_exchange_rates`) con fallback a fecha más cercana (607 filas ajustadas). Control operativo de reclamos vía migración `0002_handoff_tickets.sql`. |

---

## 2. Hallazgos de Datos y Correcciones Realizadas

Durante el perfilado de datos y diseño del pipeline (detallado en `docs/calidad_datos.md`), se identificaron y resolvieron inconsistencias críticas de negocio:

- **Normalización de Países:** Corrección de la entidad México (sin tilde en 48,515 registros) en tablas transaccionales y de agentes.
- **Comportamiento Monetario por País:**
  - Se validó que el 100% de las transacciones de México se procesan en USD (2,105,794 filas), eliminando conversiones innecesarias.
  - Para COP y ARS, `amount_usd` fue recalculado formalmente mediante la fórmula:
    $$\text{monto\_usd} = \text{COALESCE}(\text{amount\_usd}, \text{amount} \times \text{tasa\_cambio})$$
- **Imputación Estructurada de Fraud Score:**
  - ~20% de las filas presentaban `fraud_score` nulo (885,157 registros). Se aplicó imputación por mediana diferenciando según la bandera `is_fraud` (~15.0 para no fraude, ~48.9 para fraude), registrando cada ajuste con la columna booleana `fraud_score_imputed`.
- **Desacople de Reclamos y Dueños:**
  - Se identificó que la tabla histórica `complaints` no asociaba el cliente reclamante con el dueño real del producto en el 100% de los casos (44,570 filas). Por ello, se aisló `complaints` para evitar sesgar el buscador y se garantizó la búsqueda sobre `transactions` donde la coincidencia cliente-producto es del 100%.

---

## 3. Buscador de Transacciones y Recuperación (`txn_buscar.py`)

El componente `txn_buscar.py` resuelve la localización precisa de la transacción sobre la cual el usuario realiza un reclamo, asegurando aislamiento de seguridad RLS (`customer_id` autenticado).

### Puntuación y Criterios de Elección
- **Ventana de Búsqueda:** Últimos **120 días** desde la fecha de consulta.
- **Scoring por Atributos:**
  - **Coincidencia de Monto:** Exacto ($\le 0.5\%$ diferencia): +5 puntos. Cercano ($\le 5\%$ diferencia): +3 puntos.
  - **Coincidencia de Fecha:** $\pm 1$ día respecto a la fecha del evento o procesamiento.
  - **Coincidencia de Comercio / Merchant:** Normalización de nombres de comercios.
- **Uso de Filtros:** Selección unívoca cuando el puntaje es $\ge 3$ sin empates; solicitud de confirmación interactiva en caso contrario.

### Resultados de Evaluación (`eval/recall_txn_buscar.py`)
Evaluado sobre una muestra de **1,500 transacciones reales** y consultas sintéticas multilingües:

| Métrica | Línea Base (Última Transacción) | Buscador `txn_buscar.py` | Impacto |
| :--- | :--- | :--- | :--- |
| **Recall@3** | 66.0% | **~100.0%** | +34.0% incremento absoluto |
| **Precisión de Selección** | < 67.0% | **> 95.0%** | +28.0% en ventanas densas |

---

## 4. Clasificación de Intenciones y Contratos Pydantic (`contrato.py`)

Definición de especificaciones y modelos de datos Pydantic para el servicio Python `/classify` (especificado en `docs/guia_etiquetado.md`):

- **Etiquetas de Intención Aceptadas:**
  - `cargo_no_reconocido`, `cobro_indebido`, `otro_reclamo`, `ambigua`, `fuera_de_alcance`.
- **Subtipos de Cobro Indebido:**
  - `comision` (evaluado contra tipo *Adjustment* o palabras clave de comisión).
  - `duplicado` (misma transacción, monto y comercio dentro de 24h).
  - `compra` (cualquier otro cobro).
- **Criterio de Confianza:** Umbral estricto $\ge 0.7$. Si el modelo retorna un valor inferior a 0.7, la intención se degrada automáticamente a `ambigua` para requerir aclaración.

---

## 5. Calidad de Ingeniería y Pruebas Automatizadas

El proyecto incluye un conjunto de pruebas unitarias y de integración que validan el comportamiento del pipeline contra la base de datos PostgreSQL RDS real (`data_pipeline/tests/`):

- **`test_quality.py`:**
  - Unicidad de Claves Primarias (PK) en todas las capas.
  - Validación de rango de fechas de procesamiento ($\pm 1$ día).
  - Consistencia de desviación en `monto_usd` ($\le 3\%$).
  - Validación de rango estricto de `fraud_score` ($0 \le \text{score} \le 100$).
  - Normalización correcta de entidades de país (México).
- **`test_silver_pipeline.py`:**
  - 55 pruebas unitarias cubriendo funciones de transformación, mapeo de monedas y limpieza.
- **Higiene de Repositorio:**
  - Hooks de pre-commit con `nbstripout` y `.gitattributes` con `eol=lf` para prevenir la filtración de datos de clientes y salidas de notebooks en Git.

---

## 6. Guía de Ejecución

### Ejecución del Pipeline Medallion Completo
```bash
# Correr pipeline completo (Bronze -> Silver -> Gold -> Quality Check)
python -m data_pipeline.etl all --force

# Correr solo pruebas de calidad
python -m data_pipeline.etl quality

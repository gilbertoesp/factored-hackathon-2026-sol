# Calidad de datos: pipeline medallion

Medido el 2026-10-02 sobre PostgreSQL (esquemas `bronze` → `silver` → `gold`).
Las pruebas viven en `data_pipeline/tests/test_quality.py` y se ejecutan con
`python -m data_pipeline.etl quality` (o `pytest data_pipeline/tests/test_quality.py`).

## Resultado de las pruebas

| Prueba | Qué verifica | Resultado |
|---|---|---|
| `test_pk_unica` | PK única y no nula en silver (10 tablas) y gold (2 tablas) | OK |
| `test_process_date_dentro_de_un_dia` | `abs(process_date - transaction_date::date) <= 1` | OK (0 violaciones) |
| `test_fechas_en_rango` | `transaction_date` entre 2023-01-01 y ahora | OK |
| `test_monto_usd_consistente` | `monto_usd` no nulo y > 0; en USD igual a `amount`; desvío de conversión ≤ 3 % | OK |
| `test_fraud_score_en_rango` | `fraud_score` en [0, 100] y nulos ≤ 30 % | OK |
| `test_disputes_rechaza_fraud_score_invalido` | La migración 0002 acepta 100 y rechaza 101 (con rollback) | OK |

Las pruebas de PK de `campaign_sends`, `digital_events` y `satisfaction_surveys` se saltan
porque esas tablas silver aún no se han construido.

## Conciliación bronze → silver

Sin pérdidas ni cuarentena: `silver.silver_quarantine` tiene 0 filas.

| Tabla | Filas bronze | Filas silver |
|---|---|---|
| transactions | 4.425.008 | 4.425.008 |
| products | 400.000 | 400.000 |
| call_center_interactions | 686.296 | 686.296 |
| call_transcripts | 171.321 | 171.321 |
| complaints | 67.095 | 67.095 |
| customers | 150.000 | 150.000 |
| daily_exchange_rates | 13.164 | 13.164 |
| branches / service_agents / marketing_campaigns | 350 / 1.200 / 200 | igual |

El perfilado no encontró PK duplicadas en ninguna tabla (`profile.out`).

## Correcciones y hallazgos clave

1. **México opera en USD.** Las transacciones con `transaction_country = 'México'` tienen
   `currency = 'USD'` en el 100 % de los casos (2.105.794 filas): no se convierten (tasa 1; `monto_usd = amount`).
   Hay cruces de país/moneda esperables en datos sintéticos (p. ej. Argentina en COP),
   por lo que la moneda se toma siempre de la transacción, no del país.
2. **`amount_usd` en COP/ARS.** En silver, `amount_usd` de origen solo viene informado en COP y ARS
   (nunca en USD). Gold recalcula `amount_usd = amount × exchange_rate` con la tasa del día
   (`daily_exchange_rates`, 1 unidad de moneda origen = `rate` USD). Si falta la tasa del día se usa la
   más cercana en fecha y se marca `fx_fallback = true` (607 filas). El valor recalculado difiere del
   de origen hasta un 2,1 % (por eso la tolerancia del 3 % en la prueba).
3. **`monto_usd`.** Se expone en la vista `gold.transactions_monto_usd`: en USD es
   `COALESCE(amount_usd_source, amount)`; en otras monedas, el `amount_usd` convertido.
4. **Vinculación directa en transacciones.** Cada transacción trae `customer_id` y `product_id`;
   0 huérfanos contra `silver.customers` y `silver.products`, por lo que no se requiere un cruce
   intermedio para atribuir una transacción a un cliente.
5. **`process_date`.** Siempre es el mismo día o el día anterior a `transaction_date` (diferencias 0 y −1,
   3,3 M y 1,1 M filas), dentro de la ventana de ±1 día.
6. **Casteo seguro.** Los valores no casteables quedan en NULL; no se imputa 0 (para no fabricar
   `fraud_score = 0`).

## Problemas conocidos (no corregidos)

- **`fraud_score` nulo en 885.157 transacciones (20 %).** Los valores presentes están en [0, 99,99].
  1.755 transacciones con `is_fraud = true` tienen `fraud_score < 50`. Hay que decidir cómo tratar los nulos
  antes de usar el score en el motor.
- **País con dos grafías:** `Mexico` y `México` (40.515 y 2.105.794 filas). Normalizar antes de agrupar por país.
- **FK "soft" de sucursales:** `service_agents.assigned_branch_id` (69 % huérfanos) y
  `customers.registration_branch_id` (100 % huérfanos) solo se reportan, no se ponen en cuarentena.
- **Emails repetidos:** 150.000 clientes pero solo 91.289 emails distintos (sin resolver).
- **Silver incompleto:** faltan `campaign_sends`, `digital_events` (15,6 M filas) y `satisfaction_surveys`.
  El gold no depende de ellas.

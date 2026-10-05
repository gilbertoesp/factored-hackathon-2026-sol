# Recall@3 de txn.buscar (consultas sintéticas)

Objetivos: 1500 transacciones reales Approved; ventana de 120 días, margen de fecha ±1 día. Transacciones por ventana: mediana 5, máx 19. Semilla fija. Ver `eval/recall_txn_buscar.py` para la definición de líneas base y escenarios.


## Ventanas: todas

| Escenario | n | última | monto exacto | motor | motor: seleccionó | precisión al seleccionar |
|---|---|---|---|---|---|---|
| completa | 1500 | 66.1% | 100.0% | 100.0% | 99.9% | 100.0% |
| monto_fecha | 1500 | 66.1% | 100.0% | 100.0% | 99.9% | 100.0% |
| monto_aprox | 1500 | 66.1% | 72.0% | 99.9% | 35.7% | 98.9% |
| fecha_comercio | 1500 | 66.1% | 66.1% | 100.0% | 23.8% | 100.0% |
| solo_monto | 1500 | 66.1% | 100.0% | 100.0% | 98.9% | 100.0% |

## Ventanas: densas

| Escenario | n | última | monto exacto | motor | motor: seleccionó | precisión al seleccionar |
|---|---|---|---|---|---|---|
| completa | 172 | 32.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| monto_fecha | 172 | 32.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| monto_aprox | 172 | 32.0% | 45.3% | 100.0% | 38.4% | 95.5% |
| fecha_comercio | 172 | 32.0% | 32.0% | 100.0% | 25.0% | 100.0% |
| solo_monto | 172 | 32.0% | 100.0% | 100.0% | 98.3% | 100.0% |

## Cómo leer estos números

- Son consultas **sintéticas** sobre transacciones reales: no hay vínculo reclamo → transacción en los datos.
  Para llevar esto a producción hace falta medirlo con reclamos reales etiquetados.
- Con monto exacto y varios decimales casi no hay colisiones, por eso la línea base "monto exacto" también llega a
  100 %. La ventaja del motor aparece cuando el monto es aproximado o falta (`monto_aprox`, `fecha_comercio`):
  ahí supera a ambas líneas base por 28 a 68 puntos en ventanas densas.
- "Seleccionó" es el porcentaje de casos en que el motor elige un único candidato; con pistas débiles prefiere no elegir
  (el motor de decisión debe pedir confirmación al cliente) y la precisión al seleccionar se mantiene ≥ 95 %.
- La consulta del cliente se simula hasta 110 días después de la transacción y se acota a 2026-06-18, fin de los datos.

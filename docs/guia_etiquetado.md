# Guía de etiquetado y contrato de `/classify` (M01, M02)

Contrato en código: `motor/contrato.py` (pydantic). Pruebas: `tests/test_contrato.py`.

## Respuesta del servicio

```json
{"intent": "cobro_indebido", "subtype": "duplicado", "confidence": 0.91, "language": "es-CO"}
```

`language` ∈ `es-MX`, `es-CO`, `es-AR`, `pt-BR`. **Umbral de confianza mínimo: 0,7.** Con `confidence < 0.7` la
intención efectiva pasa a `ambigua` y se descarta el subtipo (`motor.contrato.efectiva`). Con 0,70 exacto se acepta.

## Intenciones

| intent | Cuándo etiquetar | subtype |
|---|---|---|
| `cargo_no_reconocido` | El cliente no reconoce un cargo ("yo no hice esta compra"). | — |
| `cobro_indebido` | Reconoce el cargo pero afirma que no corresponde. | **obligatorio:** `comision`, `duplicado` o `compra` |
| `otro_reclamo` | Reclamo bancario válido que no es de cargos (app, sucursal, servicio). | — |
| `ambigua` | No se puede decidir entre intenciones o falta información. | — |
| `fuera_de_alcance` | Pedido que este servicio no atiende. | `bloqueo_tarjeta` u `otro` |

Subtipos de `cobro_indebido` (los usan las reglas de cobro indebido, ver tabla de reglas más abajo):

- `comision`: me cobraron una comisión, cuota de manejo o cargo del banco ("¿por qué me cobran mantenimiento?").
- `duplicado`: el mismo cobro aparece dos veces ("me cobraron dos veces lo mismo").
- `compra`: cobro de una compra concreta que el cliente discute (monto incorrecto, no entregada).

Los subtipos del clasificador son lo que dice el cliente; `motor/subtipo_cobro.py` los verifica contra los
datos de la transacción (ajuste sin comercio → comisión; mismo monto/comercio en ≤ 10 min → duplicado).

## Reglas de decisión al etiquetar

1. "No reconozco" gana sobre "me cobraron de más": si el cliente niega haber hecho la operación → `cargo_no_reconocido`.
2. Si el texto mezcla dos intenciones y ninguna domina → `ambigua`.
3. Bloqueo de tarjeta, pérdida o robo de la tarjeta sin cargo en disputa → `fuera_de_alcance` / `bloqueo_tarjeta`.
   Si además hay un cargo que no reconoce → `cargo_no_reconocido`.
4. Saludos o textos sin contenido → `ambigua`. Nunca inventar un subtipo.
5. Etiquetar el idioma/variante del texto, no el del cliente en el sistema.

Ejemplos:

| Texto | Etiqueta |
|---|---|
| "No reconozco este cargo de $50 en Super Ahorro" (es-MX) | `cargo_no_reconocido` |
| "Me cobraron dos veces la misma compra" (es-CO) | `cobro_indebido` / `duplicado` |
| "Che, ¿qué es este cargo por mantenimiento de cuenta?" (es-AR) | `cobro_indebido` / `comision` |
| "A compra de ontem veio com valor errado" (pt-BR) | `cobro_indebido` / `compra` |
| "La app no me deja entrar" (es-MX) | `otro_reclamo` |
| "Perdí mi tarjeta, bloqueénla" (es-CO) | `fuera_de_alcance` / `bloqueo_tarjeta` |
| "Hola, necesito ayuda con mi cuenta" (es-AR) | `ambigua` |

## Tabla de reglas

Fuente: matriz de decisión del motor (`rules.json` en `feat/rules-engine`). Las de cobro indebido:

| Regla | Condición | Acción |
|---|---|---|
| R21 | comisión ≤ 25 USD y primera en 12 meses | reversión automática |
| R22 | comisión sobre el límite o no es la primera | reclamo y asesor |
| R23 | duplicado: mismo comercio y monto en ≤ 10 min | revertir el segundo (≤ límite) o reclamo y asesor |
| R29 | compra reconocida con monto o cobro incorrecto | reclamo a back office de disputas |

Por tanto el subtipo `comision` alimenta R21/R22, `duplicado` R23 y `compra` R29.

## Dataset de entrenamiento (M02): especificación para la revisión con Manuel

- 800–1.200 ejemplos en JSONL: `{"text", "intent", "subtype", "language", "source"}`.
- Cuotas mínimas: por idioma (es-MX, es-CO, es-AR, pt-BR) ≥ 150 ejemplos cada uno; por intención ≥ 100;
  `cobro_indebido`: los 3 subtipos con ≥ 40 cada uno; `ambigua` y `fuera_de_alcance` ≥ 100 entre ambas.
- Revisión: 10 % doble etiquetado, concordancia (kappa) ≥ 0,8; textos sin datos personales reales.
- Estado: **la revisión con Manuel está pendiente**; este repositorio no contiene el dataset todavía.

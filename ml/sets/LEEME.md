# Set de prueba de intenciones (M03)

`banking77_prueba.jsonl`: 240 consultas bancarias, 60 por clase, en inglés (original), español y portugués.

## Origen y licencia

- Fuente: split de prueba de BANKING77 (Casanueva et al., 2020), consultas escritas por personas.
  <https://github.com/PolyAI-LDN/task-specific-datasets>
- Licencia: CC BY 4.0. Se redistribuye una muestra traducida, con atribución.
- No contiene datos del dataset del banco ni de clientes.

## Cómo se construyó

1. `preparar_banking77.py` descarga el split de prueba y se queda con las intenciones de `MAPEO_BANKING77` (`intents.py`).
2. Toma 60 ejemplos por clase, repartidos entre sus intenciones, ordenando por md5 del texto. La selección es determinista y no depende de ningún modelo.
3. El campo `en` es el texto original. `es` y `pt` son traducciones.

## Estado

- **Traducción: automática, sin revisión humana.** Cada fila lleva `"traduccion": "automatica"` y `"revisado": false`. M03 pide revisión por una persona; al revisar una fila se corrige el texto y se pone `"revisado": true`.
- **Mapeo de intenciones: propuesta.** Falta validarlo contra la guía de etiquetado (M01). Las intenciones dudosas están en `PENDIENTES_M01` y no entran al set.
- El español es neutro; no hay variantes MX, CO y AR.

## Uso

Este set es solo de prueba. No se usa para entrenar ni para ajustar patrones o umbrales.

```bash
python preparar_banking77.py   # regenera la muestra en inglés y verifica que el set traducido coincida
python evaluar_baseline.py     # métricas de la línea base por palabras clave (M04)
```

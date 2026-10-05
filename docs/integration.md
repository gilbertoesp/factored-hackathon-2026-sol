# Rama `integration`: unión de las cuatro líneas de trabajo

Construida sobre `origin/feat/rules-engine` (Flor; ya contiene `feat/webhook` de Gilberto) → merge de
`feat/hackathon-data-pipeline_v1` (Manuel, comparte ancestro con `main`) → merge de `feat/medallion-pipeline`
(Diego, historia aislada: `--allow-unrelated-histories`). Es una propuesta para revisar, no una decisión tomada.

## Conflictos y cómo se resolvieron

| Archivo | Resolución | Decisión pendiente |
|---|---|---|
| `.env.example`, `.gitignore`, `.gitattributes` | unión de todos los lados | no |
| `docker-compose.yml` | base de Flor (loopback, `:?` fail-closed) + `data-processor` de Manuel + servicio `medallion` (perfil propio) | no |
| `data-processor` (Manuel) | se quitó `DB_PASSWORD=postgres` fijo; usa `POSTGRES_*` como el resto | confirmar con Manuel |
| `data_pipeline/etl.py` | conserva el medallion; el ETL de Manuel pasó a `etl_bank.py` (imports corregidos) | **sí: ¿un solo ETL?** |
| `supabase/migrations/0002_handoff_tickets.sql` | gana la de Flor; la nuestra está en `supabase/migrations_rds/` | **sí: esquema de `handoff_tickets` y base (RDS o Supabase)** |
| `README.MD` / `README.md` | el nuestro pasó a `docs/README_data_ml.md` (evita el choque por mayúsculas) | no |
| `silver_report.json` | fuera del repositorio e ignorado | no |

## Colisiones que git no marca (siguen abiertas)

- Dos `txn_buscar`: `motor/txn_buscar.py` (SQLAlchemy, gold) y `data_pipeline/txn_buscar.py` (D10, pydantic, esquema `bank`).
- Dos conjuntos de intenciones: `motor/contrato.py` (subtipos, 4 variantes regionales) y `ml/intents.py` (4 clases, es/pt/en).
- Dos `requirements`: raíz (medallion) y `data_pipeline/requirements.txt` (pinned, ETL bank).
- Dos paquetes `tests`: `tests/` (raíz) y `data_pipeline/tests/`; correr cada suite por separado (ver abajo).
- El backend TypeScript aún no llama a `/classify` ni a `txn.buscar`.

## Cómo verificar

```bash
python -m pytest tests -q                          # contrato, txn.buscar, evaluación (omite lo que necesita .motor/)
bash eval/preparar_motor.sh && python -m eval.contra_motor
(cd data_pipeline && python -m pytest tests -q)    # ETL de Manuel
(cd ml && python -m pytest tests -q)               # baseline de Manuel
(cd backend && bun test)                           # motor de reglas (requiere bun)
```

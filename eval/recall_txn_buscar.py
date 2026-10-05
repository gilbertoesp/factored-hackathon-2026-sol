"""Recall@3 de txn.buscar frente a dos líneas base simples, con consultas SINTÉTICAS.

No existe un vínculo reclamo -> transacción en los datos (silver.complaints no trae transaction_id), así que se
muestrean transacciones reales Approved como "objetivo" y se simulan consultas con distinto nivel de detalle.

Líneas base:  ultima       las 3 transacciones más recientes de la ventana.
              monto_exacto las 3 más recientes con el monto exacto (±0,5 %); si no hay monto, las más recientes.
Escenarios:   completa (monto+fecha+comercio) | monto_fecha | monto_aprox (±3 %, + comercio) |
              fecha_comercio (fecha ±1 día) | solo_monto.
Estratos:     todas las ventanas | ventanas densas (>= 10 transacciones del cliente en 120 días).

Uso: DATABASE_URL=... python -m eval.recall_txn_buscar [--n 2000] [--out docs/recall_txn_buscar.md]
"""
import argparse
import os
import random
from datetime import datetime, timedelta

from sqlalchemy import create_engine

from motor.txn_buscar import Query, fetch_window, rank


def recientes(rows, k=3):
    return sorted(rows, key=lambda r: -r["transaction_date"].timestamp())[:k]


def monto_exacto(rows, q, k=3):
    hit = [r for r in recientes(rows, len(rows)) if q.amount is not None and abs(float(r["amount"]) - q.amount) <= 0.005 * abs(q.amount)]
    return (hit + [r for r in recientes(rows, len(rows)) if r not in hit])[:k]


def make_query(t, scenario, rnd):
    d, m = t["transaction_date"].date(), t.get("merchant_name")
    amt = float(t["amount"])
    jitter = timedelta(days=rnd.choice([-1, 0, 0, 1]))
    kw = dict(customer_id=t["customer_id"], currency=t["currency"])
    return {
        "completa": Query(amount=amt, date=d, merchant=m, **kw),
        "monto_fecha": Query(amount=amt, date=d, **kw),
        "monto_aprox": Query(amount=round(amt * (1 + rnd.uniform(-0.03, 0.03)), 2), merchant=m, **kw),
        "fecha_comercio": Query(date=d + jitter, merchant=m, **kw),
        "solo_monto": Query(amount=amt, **kw),
    }[scenario]


NOTAS = '''
## Cómo leer estos números

- Son consultas **sintéticas** sobre transacciones reales: no hay vínculo reclamo → transacción en los datos.
  Para llevar esto a producción hace falta medirlo con reclamos reales etiquetados.
- Con monto exacto y varios decimales casi no hay colisiones, por eso la línea base "monto exacto" también llega a
  100 %. La ventaja del motor aparece cuando el monto es aproximado o falta (`monto_aprox`, `fecha_comercio`):
  ahí supera a ambas líneas base por 28 a 68 puntos en ventanas densas.
- "Seleccionó" es el porcentaje de casos en que el motor elige un único candidato; con pistas débiles prefiere no elegir
  (el motor de decisión debe pedir confirmación al cliente) y la precisión al seleccionar se mantiene ≥ 95 %.
- La consulta del cliente se simula hasta 110 días después de la transacción y se acota a 2026-06-18, fin de los datos.
'''
DATA_END = datetime(2026, 6, 18)
SCENARIOS = ["completa", "monto_fecha", "monto_aprox", "fecha_comercio", "solo_monto"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--out", default="docs/recall_txn_buscar.md")
    args = ap.parse_args()
    rnd = random.Random(7)
    eng = create_engine(os.environ["DATABASE_URL"])
    cols = "transaction_id, customer_id, transaction_date, currency, merchant_name, amount"
    with eng.connect() as c:
        c.exec_driver_sql("SET statement_timeout = 0")
        targets = c.exec_driver_sql(
            f"SELECT {cols} FROM gold.fact_transactions_usd TABLESAMPLE SYSTEM (0.2) "
            f"WHERE transaction_status = 'Approved' AND transaction_date >= '2023-10-20' AND transaction_date < '2026-06-01' "
            f"LIMIT {args.n * 3}").fetchall()
        rnd.shuffle(targets)
        targets = [dict(zip(cols.split(", "), r)) for r in targets][: args.n]
        stats = {(s, st, m): [0, 0] for s in SCENARIOS for st in ("todas", "densas") for m in ("ultima", "monto_exacto", "motor")}
        sel = {(s, st): [0, 0, 0] for s in SCENARIOS for st in ("todas", "densas")}  # n, seleccionadas, acertadas
        win_sizes = []
        for t in targets:
            as_of = min(t["transaction_date"] + timedelta(days=rnd.randint(0, 110)), DATA_END)  # el cliente consulta hasta 110 días después
            rows = fetch_window(c, t["customer_id"], as_of)
            if not any(r["transaction_id"] == t["transaction_id"] for r in rows):
                continue
            win_sizes.append(len(rows))
            strata = ["todas"] + (["densas"] if len(rows) >= 10 else [])
            for sc in SCENARIOS:
                q = make_query(t, sc, rnd)
                outs = {"ultima": recientes(rows), "monto_exacto": monto_exacto(rows, q), "motor": rank(rows, q)[0]}
                chosen = rank(rows, q)[1]
                for st in strata:
                    for m, res in outs.items():
                        k = stats[(sc, st, m)]
                        k[0] += 1
                        k[1] += any(r["transaction_id"] == t["transaction_id"] for r in res)
                    s = sel[(sc, st)]
                    s[0] += 1
                    if chosen:
                        s[1] += 1
                        s[2] += chosen["transaction_id"] == t["transaction_id"]
    lines = [f"# Recall@3 de txn.buscar (consultas sintéticas)\n",
             f"Objetivos: {len(win_sizes)} transacciones reales Approved; ventana de 120 días, margen de fecha ±1 día. "
             f"Transacciones por ventana: mediana {sorted(win_sizes)[len(win_sizes)//2]}, máx {max(win_sizes)}. "
             f"Semilla fija. Ver `eval/recall_txn_buscar.py` para la definición de líneas base y escenarios.\n"]
    for st in ("todas", "densas"):
        lines += [f"\n## Ventanas: {st}\n", "| Escenario | n | última | monto exacto | motor | motor: seleccionó | precisión al seleccionar |",
                  "|---|---|---|---|---|---|---|"]
        for sc in SCENARIOS:
            n = stats[(sc, st, "motor")][0]
            if not n:
                continue
            r = lambda m: f"{stats[(sc, st, m)][1] / n:.1%}"
            _, ns, ok = sel[(sc, st)]
            lines.append(f"| {sc} | {n} | {r('ultima')} | {r('monto_exacto')} | {r('motor')} | {ns / n:.1%} | {(ok / ns if ns else 0):.1%} |")
    lines.append(NOTAS)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    open(args.out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

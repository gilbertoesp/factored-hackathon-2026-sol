"""Genera tests/fixtures/cobros_indebidos.json (datos 100 % sintéticos, semilla fija).

Uso: python tests/fixtures/generar_cobros.py
"""
import json
import os
import random
from datetime import datetime, timedelta

rnd = random.Random(2026)
MERCHANTS = ["Super Ahorro", "Restaurante El Buen Sabor", "Tienda Don José", "Mercado Central"]
T0 = datetime(2026, 5, 1, 10, 0)


def txn(i, cust, **kw):
    base = dict(transaction_id=f"TXN-{i:05d}", customer_id=cust, transaction_date=T0 + timedelta(hours=rnd.randint(0, 600)),
                transaction_type="Purchase", transaction_status="Approved", merchant_name=rnd.choice(MERCHANTS),
                amount=round(rnd.uniform(5, 300), 2), currency="USD")
    base.update(kw)
    return base


cases, n = [], 0
for k in range(10):  # comisión: ajuste sin comercio
    n += 1; sel = txn(n, f"CLI-S{k}", transaction_type="Adjustment", merchant_name=None)
    others = [txn(n * 10 + j, f"CLI-S{k}") for j in range(1, 4)]
    cases.append(dict(name=f"comision_ajuste_{k}", expected="comision", selected=sel, others=others))
for k in range(5):  # comisión: comercio con palabra de comisión
    n += 1; sel = txn(n, f"CLI-F{k}", merchant_name=rnd.choice(["Comisión por mantenimiento", "Fee mensual", "Cargo por membresía"]))
    cases.append(dict(name=f"comision_comercio_{k}", expected="comision", selected=sel, others=[txn(n * 10 + 1, f"CLI-F{k}")]))
for k in range(10):  # duplicado: mismo monto/comercio en < 24 h
    n += 1; sel = txn(n, f"CLI-D{k}")
    dup = dict(sel, transaction_id=f"TXN-D{k:04d}", transaction_date=sel["transaction_date"] + timedelta(minutes=rnd.randint(1, 600)))
    cases.append(dict(name=f"duplicado_{k}", expected="duplicado", selected=sel, others=[dup, txn(n * 10 + 1, f"CLI-D{k}")]))
for k in range(5):  # NO duplicado: igual monto pero 3 días después, o la copia fue revertida
    n += 1; sel = txn(n, f"CLI-N{k}")
    other = dict(sel, transaction_id=f"TXN-N{k:04d}",
                 transaction_date=sel["transaction_date"] + timedelta(days=3 if k % 2 else 0, minutes=5),
                 transaction_status="Approved" if k % 2 else "Reversed")
    cases.append(dict(name=f"no_duplicado_{k}", expected="compra", selected=sel, others=[other]))
for k in range(10):  # compra normal
    n += 1; sel = txn(n, f"CLI-C{k}")
    cases.append(dict(name=f"compra_{k}", expected="compra", selected=sel, others=[txn(n * 10 + j, f"CLI-C{k}") for j in range(1, 4)]))

out = os.path.join(os.path.dirname(__file__), "cobros_indebidos.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(cases, f, indent=1, default=lambda d: d.isoformat(), ensure_ascii=False)
print(len(cases), "casos ->", out)

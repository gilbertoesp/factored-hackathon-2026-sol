#!/usr/bin/env python3
"""Prueba end-to-end de silver_pipeline.py con fallos inyectados en esquemas temporales.

Copia una muestra de bronze a zz_bronze, inyecta duplicados / nulos críticos / huérfanos /
valores no casteables, corre el pipeline (con Great Expectations) y verifica el resultado.
Requiere DATABASE_URL. No toca bronze/silver reales.
"""
import os
import subprocess
import sys

from sqlalchemy import create_engine, text

URL = os.environ["DATABASE_URL"]
e = create_engine(URL)
B, S = "zz_bronze", "zz_silver"


def ex(sql, **p):
    with e.begin() as c:
        return c.execute(text(sql), p)


def val(sql, **p):
    with e.connect() as c:
        return c.execute(text(sql), p).scalar()


def seed():
    ex(f"DROP SCHEMA IF EXISTS {B} CASCADE; DROP SCHEMA IF EXISTS {S} CASCADE; CREATE SCHEMA {B}")
    ex(f"CREATE TABLE {B}.branches AS SELECT * FROM bronze.branches")
    ex(f"CREATE TABLE {B}.customers AS SELECT * FROM bronze.customers ORDER BY customer_id LIMIT 500")
    ex(f"CREATE TABLE {B}.products AS SELECT * FROM bronze.products WHERE customer_id IN (SELECT customer_id FROM {B}.customers)")
    ex(f"""CREATE TABLE {B}.transactions AS SELECT * FROM bronze.transactions
           WHERE customer_id IN (SELECT customer_id FROM {B}.customers)
             AND product_id IN (SELECT product_id FROM {B}.products) LIMIT 3000""")


def inject():
    # ids de ejemplo
    ids = [r[0] for r in ex(f"SELECT transaction_id FROM {B}.transactions ORDER BY transaction_id LIMIT 12")]
    T = dict(zip("abcdefghijkl", ids))
    # a: duplicado con versión MÁS NUEVA y distinto monto -> debe ganar
    ex(f"""INSERT INTO {B}.transactions SELECT * FROM {B}.transactions WHERE transaction_id=:i""", i=T["a"])
    ex(f"""UPDATE {B}.transactions SET process_date='2099-01-01', amount='777.77'
           WHERE ctid=(SELECT max(ctid) FROM {B}.transactions WHERE transaction_id=:i)""", i=T["a"])
    # b: duplicado exacto de version vieja (mismo process_date) -> desempata _ingested_at; sigue 1 sola fila
    ex(f"""INSERT INTO {B}.transactions SELECT * FROM {B}.transactions WHERE transaction_id=:i""", i=T["b"])
    # c/d/e: nulos críticos
    ex(f"UPDATE {B}.transactions SET customer_id='' WHERE transaction_id=:i", i=T["c"])
    ex(f"UPDATE {B}.transactions SET amount='' WHERE transaction_id=:i", i=T["d"])
    ex(f"UPDATE {B}.transactions SET currency='   ' WHERE transaction_id=:i", i=T["e"])
    # f: FK huérfana
    ex(f"UPDATE {B}.transactions SET customer_id='CLI-NOPE' WHERE transaction_id=:i", i=T["f"])
    # g: monto no casteable en columna requerida
    ex(f"UPDATE {B}.transactions SET amount='abc' WHERE transaction_id=:i", i=T["g"])
    # h: fraud_score inválido (anulable) -> NULL, NO cuarentena; i: fraud_score vacío -> NULL
    ex(f"UPDATE {B}.transactions SET fraud_score='xx' WHERE transaction_id=:i", i=T["h"])
    ex(f"UPDATE {B}.transactions SET fraud_score='' WHERE transaction_id=:i", i=T["i"])
    # j: fecha imposible en columna requerida
    ex(f"UPDATE {B}.transactions SET process_date='2023-02-30' WHERE transaction_id=:i", i=T["j"])
    # producto con cliente inexistente -> cuarentena; sus transacciones -> cascada fk_product_id
    pid = val(f"SELECT product_id FROM {B}.products p WHERE EXISTS (SELECT 1 FROM {B}.transactions t WHERE t.product_id=p.product_id) LIMIT 1")
    ex(f"UPDATE {B}.products SET customer_id='CLI-GHOST' WHERE product_id=:p", p=pid)
    n_casc = val(f"SELECT count(*) FROM {B}.transactions WHERE product_id=:p AND transaction_id NOT IN (:c,:d,:e,:f,:g,:j)",
                 p=pid, c=T["c"], d=T["d"], e=T["e"], f=T["f"], g=T["g"], j=T["j"])
    # cliente duplicado: la versión más nueva (last_updated) gana
    cid = val(f"SELECT customer_id FROM {B}.customers ORDER BY customer_id OFFSET 5 LIMIT 1")
    ex(f"INSERT INTO {B}.customers SELECT * FROM {B}.customers WHERE customer_id=:c", c=cid)
    ex(f"""UPDATE {B}.customers SET last_updated='2099-01-01 00:00:00', first_name='NUEVO'
           WHERE ctid=(SELECT max(ctid) FROM {B}.customers WHERE customer_id=:c)""", c=cid)
    return T, pid, cid, n_casc


def main():
    seed()
    T, pid, cid, n_casc = inject()
    env = dict(os.environ, BRONZE_SCHEMA=B, SILVER_SCHEMA=S, TABLES="branches,customers,products,transactions")
    r = subprocess.run([sys.executable, "silver_pipeline.py"], env=env, capture_output=True, text=True)
    print(r.stdout[-6000:], r.stderr[-2000:])
    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    check("pipeline + GE terminan con exit 0", r.returncode == 0)
    check("dup más nuevo gana (amount=777.77)",
          str(val(f"SELECT amount FROM {S}.transactions WHERE transaction_id=:i", i=T["a"])) == "777.77")
    check("dup perdedor en cuarentena (duplicate_pk)",
          val(f"SELECT count(*) FROM {S}.silver_quarantine WHERE source_table='transactions' AND record_key=:i AND reasons LIKE '%duplicate_pk%'", i=T["a"]) == 1)
    check("dup exacto deja 1 sola fila", val(f"SELECT count(*) FROM {S}.transactions WHERE transaction_id=:i", i=T["b"]) == 1)
    for k, reason in [("c", "null_customer_id"), ("d", "null_amount"), ("e", "null_currency"), ("f", "fk_customer_id"),
                      ("g", "invalid_amount"), ("j", "invalid_process_date")]:
        check(f"{reason} -> cuarentena y ausente de silver",
              val(f"SELECT count(*) FROM {S}.silver_quarantine WHERE source_table='transactions' AND record_key=:i AND reasons LIKE :r", i=T[k], r=f"%{reason}%") == 1
              and val(f"SELECT count(*) FROM {S}.transactions WHERE transaction_id=:i", i=T[k]) == 0)
    for k in "hi":
        check(f"fraud_score anulable ({k}) queda NULL en silver, sin cuarentena",
              val(f"SELECT count(*) FROM {S}.transactions WHERE transaction_id=:i AND fraud_score IS NULL", i=T[k]) == 1
              and val(f"SELECT count(*) FROM {S}.silver_quarantine WHERE record_key=:i", i=T[k]) == 0)
    check("producto huérfano en cuarentena (fk_customer_id)",
          val(f"SELECT count(*) FROM {S}.silver_quarantine WHERE source_table='products' AND record_key=:p AND reasons LIKE '%fk_customer_id%'", p=pid) == 1)
    check(f"cascada: {n_casc} transacciones hijas -> fk_product_id",
          val(f"SELECT count(*) FROM {S}.silver_quarantine WHERE source_table='transactions' AND reasons LIKE '%fk_product_id%'") == n_casc and n_casc > 0)
    check("cliente duplicado: gana last_updated más nuevo",
          val(f"SELECT first_name FROM {S}.customers WHERE customer_id=:c", c=cid) == "NUEVO")
    check("tipos reales en silver (amount numeric, process_date date)",
          val(f"SELECT data_type FROM information_schema.columns WHERE table_schema='{S}' AND table_name='transactions' AND column_name='amount'") == "numeric"
          and val(f"SELECT data_type FROM information_schema.columns WHERE table_schema='{S}' AND table_name='transactions' AND column_name='process_date'") == "date")
    check("conciliación bronze = silver + cuarentena (transactions)",
          val(f"SELECT count(*) FROM {B}.transactions") ==
          val(f"SELECT count(*) FROM {S}.transactions") + val(f"SELECT count(*) FROM {S}.silver_quarantine WHERE source_table='transactions'"))
    check("payload de cuarentena conserva la fila cruda",
          val(f"SELECT payload->>'customer_id' FROM {S}.silver_quarantine WHERE source_table='transactions' AND record_key=:i", i=T["f"]) == "CLI-NOPE")

    ex(f"DROP SCHEMA {B} CASCADE; DROP SCHEMA {S} CASCADE")
    print(f"\n{'TODO OK' if not fails else 'FALLARON: ' + str(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

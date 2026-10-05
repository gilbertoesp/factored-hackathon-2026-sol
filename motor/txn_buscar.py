"""txn.buscar: localiza la transacción a la que se refiere un reclamo.

Seguridad: la búsqueda SIEMPRE se acota al cliente autenticado (`customer_id` obligatorio). Un
`transaction_id` ajeno no devuelve datos: solo activa `referencesForeignTransaction`.

`rank` es una función pura (sin base de datos) para poder probarla y evaluarla; `buscar` solo añade la
consulta a Postgres (esquema gold).

Resultado de `buscar`:
  referencesForeignTransaction  True si el reclamo cita un id de transacción de OTRO cliente.
  candidates                    hasta `top_k` transacciones del cliente, mejor puntaje primero.
  selected                      el candidato elegido, o None si hay empate o evidencia insuficiente.
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta

GOLD = os.getenv("GOLD_SCHEMA", "gold")
WINDOW_DAYS = 120          # ventana hacia atrás desde `as_of`
DATE_MARGIN = 1            # ±1 día alrededor de la fecha mencionada (transaction_date o process_date)
AMOUNT_EXACT_TOL = 0.005   # 0,5 %
AMOUNT_NEAR_TOL = 0.05     # 5 %
MIN_SELECT_SCORE = 3.0     # puntaje mínimo para elegir una transacción
W_AMOUNT_EXACT, W_AMOUNT_NEAR, W_DATE, W_MERCHANT = 3.0, 1.5, 2.0, 2.0
COLUMNS = ("transaction_id", "transaction_date", "process_date", "transaction_type", "transaction_status",
           "merchant_name", "amount", "currency", "monto_usd", "fraud_score")


@dataclass
class Query:
    customer_id: str
    amount: float | None = None
    currency: str | None = None
    date: date | None = None
    merchant: str | None = None
    transaction_id: str | None = None
    as_of: datetime | None = None


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def _day(v):
    return v.date() if isinstance(v, datetime) else v


def score(row, q):
    """Puntaje de coincidencia entre una transacción y lo que dijo el cliente (0 = sin evidencia)."""
    s = 0.0
    if q.amount is not None:
        if q.currency == row["currency"]:
            refs = [row["amount"]]
        elif q.currency == "USD":
            refs = [row["monto_usd"]]
        else:  # moneda no indicada: se acepta el monto local o su equivalente en USD
            refs = [row["amount"], row["monto_usd"]]
        rel = min(abs(float(r) - q.amount) for r in refs if r is not None) / max(abs(q.amount), 1e-9)
        s += W_AMOUNT_EXACT if rel <= AMOUNT_EXACT_TOL else W_AMOUNT_NEAR if rel <= AMOUNT_NEAR_TOL else 0.0
    if q.date is not None:
        days = [abs((_day(row[k]) - q.date).days) for k in ("transaction_date", "process_date") if row.get(k)]
        if days and min(days) <= DATE_MARGIN:
            s += W_DATE
    if q.merchant:
        m, name = _norm(q.merchant), _norm(row.get("merchant_name"))
        if m and name and (m in name or name in m):
            s += W_MERCHANT
    return s


def rank(rows, q, top_k=3):
    """Ordena `rows` (dicts de un solo cliente) y devuelve (candidates, selected)."""
    scored = sorted(((score(r, q), r) for r in rows), key=lambda x: (-x[0], -_ts(x[1])))
    cands = [dict(r, score=s) for s, r in scored[:top_k]]
    selected = None
    if cands and cands[0]["score"] >= MIN_SELECT_SCORE and (len(cands) == 1 or cands[0]["score"] > cands[1]["score"]):
        selected = cands[0]
    return cands, selected


def _ts(r):
    return r["transaction_date"].timestamp()


def fetch_window(conn, customer_id, as_of):
    """Transacciones del cliente en [as_of - 120 días, as_of + 1 día]. `conn`: conexión SQLAlchemy."""
    sql = (f"SELECT {', '.join(COLUMNS)} FROM {GOLD}.transactions_monto_usd WHERE customer_id = %s "
           f"AND transaction_date >= %s AND transaction_date < %s")
    res = conn.exec_driver_sql(sql, (customer_id, as_of - timedelta(days=WINDOW_DAYS), as_of + timedelta(days=DATE_MARGIN)))
    return [dict(zip(COLUMNS, r)) for r in res.fetchall()]


def buscar(conn, q, top_k=3):
    if not q.customer_id or not q.customer_id.strip():
        raise ValueError("customer_id es obligatorio: la búsqueda siempre se acota al cliente autenticado")
    foreign = False
    if q.transaction_id:
        owner = conn.exec_driver_sql(
            f"SELECT customer_id FROM {GOLD}.fact_transactions_usd WHERE transaction_id = %s", (q.transaction_id,)).scalar()
        foreign = owner is not None and owner != q.customer_id
        if foreign:  # no se filtra ningún dato de la transacción ajena
            return dict(referencesForeignTransaction=True, candidates=[], selected=None)
    rows = fetch_window(conn, q.customer_id, q.as_of or datetime.now())
    if q.transaction_id:
        own = [r for r in rows if r["transaction_id"] == q.transaction_id]
        if own:
            c = [dict(own[0], score=float("inf"))]
            return dict(referencesForeignTransaction=False, candidates=c, selected=c[0])
    cands, selected = rank(rows, q, top_k)
    return dict(referencesForeignTransaction=False, candidates=cands, selected=selected)

from datetime import date, datetime, timedelta

import pytest

from motor.txn_buscar import Query, buscar, rank

NOW = datetime(2026, 6, 1, 12, 0)


def row(i, days_ago, amount, merchant="Super Ahorro", cur="USD", usd=None, ptype="Purchase"):
    d = NOW - timedelta(days=days_ago)
    return dict(transaction_id=i, transaction_date=d, process_date=d.date(), transaction_type=ptype,
                transaction_status="Approved", merchant_name=merchant, amount=amount, currency=cur,
                monto_usd=usd if usd is not None else amount, fraud_score=10)


ROWS = [row("A", 2, 50.0), row("B", 10, 50.0, "Mercado Central"), row("C", 30, 120.5, "Super Ahorro"),
        row("D", 31, 15000.0, None, "COP", 3.8, "Transfer")]


def test_monto_unico_se_selecciona():
    c, sel = rank(ROWS, Query("X", amount=120.5))
    assert sel["transaction_id"] == "C"


def test_monto_repetido_se_desempata_con_comercio_o_fecha():
    assert rank(ROWS, Query("X", amount=50.0, merchant="mercado central"))[1]["transaction_id"] == "B"
    q = Query("X", amount=50.0, date=(NOW - timedelta(days=2)).date())
    assert rank(ROWS, q)[1]["transaction_id"] == "A"


def test_empate_no_selecciona():
    c, sel = rank(ROWS, Query("X", amount=50.0))
    assert sel is None and {x["transaction_id"] for x in c[:2]} == {"A", "B"}


def test_margen_de_fecha_un_dia():
    q = Query("X", date=(NOW - timedelta(days=31)).date() - timedelta(days=1))  # D a 1 día; C a 2
    assert rank(ROWS, q)[0][0]["transaction_id"] == "D"
    far = Query("X", date=(NOW - timedelta(days=31)).date() + timedelta(days=3), amount=999999)
    assert rank(ROWS, far)[0][0]["score"] == 0


def test_monto_en_usd_equivalente_para_moneda_local():
    assert rank(ROWS, Query("X", amount=3.8, currency="USD"))[1]["transaction_id"] == "D"
    assert rank(ROWS, Query("X", amount=15000.0, currency="COP"))[1]["transaction_id"] == "D"


def test_sin_pistas_devuelve_recientes_sin_seleccion():
    c, sel = rank(ROWS, Query("X"))
    assert sel is None and [x["transaction_id"] for x in c] == ["A", "B", "C"]


class FakeConn:
    """Simula la conexión: gold.fact_transactions_usd {id: customer} y la ventana del cliente."""
    def __init__(self, owners, rows):
        self.owners, self.rows = owners, rows

    def exec_driver_sql(self, sql, params=()):
        conn = self

        class R:
            def scalar(s): return conn.owners.get(params[0])
            def fetchall(s): return [tuple(r[k] for k in __import__("motor.txn_buscar", fromlist=["x"]).COLUMNS) for r in conn.rows]
        return R()


def test_customer_id_obligatorio():
    with pytest.raises(ValueError):
        buscar(FakeConn({}, []), Query(""))


def test_transaccion_ajena_no_filtra_datos():
    out = buscar(FakeConn({"TXN-9": "OTRO"}, ROWS), Query("YO", transaction_id="TXN-9", as_of=NOW))
    assert out == dict(referencesForeignTransaction=True, candidates=[], selected=None)


def test_transaccion_propia_por_id():
    out = buscar(FakeConn({"A": "YO"}, ROWS), Query("YO", transaction_id="A", as_of=NOW))
    assert out["selected"]["transaction_id"] == "A" and not out["referencesForeignTransaction"]

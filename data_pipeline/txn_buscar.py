"""D10: contrato tipado y verificador de la herramienta txn.buscar.

La herramienta solo puede devolver transacciones del cliente de la sesión. Eso
se garantiza en dos capas:
    1. La consulta SQL siempre filtra por el customer_id de la sesión; una
       transacción ajena nunca se lee de la base.
    2. ResultadoBusqueda valida, antes de salir, que cada candidata pertenece a
       ese cliente; si no, falla en vez de devolver datos de otra persona.

Reglas de la matriz que dependen de esta herramienta:
    R09  el cliente nombra una transacción que no es suya -> referencia_ajena,
         con la misma respuesta exista o no ese ID (no se confirma ni se niega).
    R10  0 candidatas en la ventana de 120 días (+/- 1 día).
    R11  varias candidatas -> top 3 con comercio, fecha y monto en moneda original.
    R12  una transacción propia nombrada por ID se devuelve aunque supere la
         ventana, con su antigüedad, para que el motor pueda derivarla.

Las reglas usan el monto normalizado a USD (monto_usd); al cliente se le muestra
la moneda original.
"""
import unicodedata
from datetime import date, timedelta
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from etl import CORTE

FECHA_REFERENCIA = CORTE.date()  # "hoy" para el agente: el dataset termina aquí
VENTANA_DIAS = 120       # searchWindowDays
TOLERANCIA_DIAS = 1      # dateToleranceDays
MAX_OPCIONES = 3         # top que se le muestra al cliente (R11)
TOLERANCIA_MONTO = 0.01  # en moneda original

Moneda = Literal["USD", "COP", "ARS"]
Estado = Literal["Approved", "Declined", "Pending", "Reversed"]
PATRON_CLIENTE = r"^CLI-[A-Z0-9]{12}$"
PATRON_TRANSACCION = r"^TRX-[A-Z0-9]{20}$"


class Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Sesion(Estricto):
    """Sesión ya autenticada. El customer_id sale del token, nunca del chat."""
    customer_id: str = Field(pattern=PATRON_CLIENTE)
    valida: bool


class Consulta(Estricto):
    """Lo que el cliente describe del movimiento."""
    fecha_desde: date
    fecha_hasta: date
    monto: Optional[float] = Field(default=None, gt=0)
    moneda: Optional[Moneda] = None
    comercio: Optional[str] = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def _rango_ordenado(self):
        if self.fecha_hasta < self.fecha_desde:
            raise ValueError("fecha_hasta es anterior a fecha_desde")
        return self


class Candidata(Estricto):
    """Una transacción del cliente. Los nombres siguen a transactionOption y Facts.transaction."""
    transactionId: str = Field(pattern=PATRON_TRANSACCION)
    customerId: str = Field(pattern=PATRON_CLIENTE, exclude=True)  # solo para verificar; no se serializa
    merchant: str
    date: date
    amount: float                      # moneda original: lo que el cliente ve
    currency: Moneda
    status: Estado
    amountUsd: float = Field(ge=0)     # normalizado: lo que usan las reglas
    fraudScore: Optional[float] = Field(default=None, ge=0, le=100)
    ageDays: int


class ResultadoBusqueda(Estricto):
    customer_id: str = Field(pattern=PATRON_CLIENTE, exclude=True)
    referencia_ajena: bool = False
    total_candidatas: int = Field(ge=0)
    candidatas: list[Candidata] = Field(max_length=MAX_OPCIONES)

    @model_validator(mode="after")
    def _solo_del_cliente_de_la_sesion(self):
        ajenas = [c.transactionId for c in self.candidatas if c.customerId != self.customer_id]
        if ajenas:
            raise ValueError(f"txn.buscar intentó devolver {len(ajenas)} transacción(es) de otro cliente")
        if self.referencia_ajena and (self.candidatas or self.total_candidatas):
            raise ValueError("una referencia ajena no puede traer candidatas")
        if self.total_candidatas < len(self.candidatas):
            raise ValueError("total_candidatas menor que las candidatas devueltas")
        return self

    def hechos_search(self, seleccionada=False, aclaraciones=0):
        """Facts.search de backend/src/rules/engine.ts."""
        return {
            "referencesForeignTransaction": self.referencia_ajena,
            "candidates": self.total_candidatas,
            "selected": seleccionada or self.total_candidatas == 1,
            "clarificationsAsked": aclaraciones,
        }


# ----------------------------------------------------------------------------
# Búsqueda
# ----------------------------------------------------------------------------
COLUMNAS = """transaction_id, customer_id, coalesce(merchant_name, transaction_type) AS comercio,
              transaction_date::date AS fecha, amount, currency, transaction_status,
              monto_usd, fraud_score"""


def normalizar(texto):
    """Sin acentos y en minúscula, para comparar comercios."""
    plano = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return " ".join(plano.lower().split())


def exigir_sesion(sesion):
    if not sesion.valida:
        raise PermissionError("txn.buscar requiere una sesión válida (R01)")


def a_candidata(fila):
    return Candidata(
        transactionId=fila["transaction_id"], customerId=fila["customer_id"], merchant=fila["comercio"],
        date=fila["fecha"], amount=float(fila["amount"]), currency=fila["currency"],
        status=fila["transaction_status"], amountUsd=float(fila["monto_usd"]),
        fraudScore=fila["fraud_score"], ageDays=(FECHA_REFERENCIA - fila["fecha"]).days)


def coincide(fila, consulta):
    if consulta.monto is not None and abs(float(fila["amount"]) - consulta.monto) > TOLERANCIA_MONTO:
        return False
    if consulta.moneda is not None and fila["currency"] != consulta.moneda:
        return False
    if consulta.comercio is not None and normalizar(fila["comercio"]) != normalizar(consulta.comercio):
        return False
    return True


def construir_resultado(sesion, consulta, filas):
    """Filtra y ordena las filas del cliente; la validación del modelo es la última barrera."""
    exigir_sesion(sesion)
    centro = consulta.fecha_desde + (consulta.fecha_hasta - consulta.fecha_desde) / 2
    elegidas = sorted((f for f in filas if coincide(f, consulta)),
                      key=lambda f: (abs((f["fecha"] - centro).days), f["transaction_id"]))
    return ResultadoBusqueda(
        customer_id=sesion.customer_id, total_candidatas=len(elegidas),
        candidatas=[a_candidata(f) for f in elegidas[:MAX_OPCIONES]])


def _filas(conn, sql, params):
    cur = conn.execute(sql, params)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, f)) for f in cur.fetchall()]


def buscar(conn, sesion, consulta, esquema="bank"):
    """Transacciones del cliente de la sesión que calzan con lo descrito (R10, R11)."""
    exigir_sesion(sesion)
    tolerancia = timedelta(days=TOLERANCIA_DIAS)
    desde = max(consulta.fecha_desde - tolerancia, FECHA_REFERENCIA - timedelta(days=VENTANA_DIAS))
    hasta = consulta.fecha_hasta + tolerancia
    filas = _filas(conn, f"""
        SELECT {COLUMNAS} FROM {esquema}.transactions
        WHERE customer_id = %(cliente)s AND transaction_date::date BETWEEN %(desde)s AND %(hasta)s
        """, {"cliente": sesion.customer_id, "desde": desde, "hasta": hasta})
    return construir_resultado(sesion, consulta, filas)


def buscar_por_id(conn, sesion, transaction_id, esquema="bank"):
    """El cliente nombra un ID. Si no es suyo, la respuesta no revela si existe (R09)."""
    exigir_sesion(sesion)
    filas = _filas(conn, f"""
        SELECT {COLUMNAS} FROM {esquema}.transactions
        WHERE transaction_id = %(id)s AND customer_id = %(cliente)s
        """, {"id": transaction_id, "cliente": sesion.customer_id})
    if not filas:
        return ResultadoBusqueda(customer_id=sesion.customer_id, referencia_ajena=True,
                                 total_candidatas=0, candidatas=[])
    return ResultadoBusqueda(customer_id=sesion.customer_id, total_candidatas=1,
                             candidatas=[a_candidata(filas[0])])

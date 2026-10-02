"""D08: casos de prueba anclados en transacciones reales para las reglas R09 a R20.

Lee la base cargada por etl.py (carga completa) y elige, de forma determinista,
transacciones reales que cumplen la condición de cada regla de la matriz de
decisión (docs/matriz_decision_es.xlsx -> backend/src/rules/rules.json).

Salidas (en casos_prueba/):
    casos_r09_r20.json    un caso por fila: cliente, transacción(es), hechos y regla esperada
    clientes_prueba.txt   customer_id de los casos; etl.py los carga con su historial
                          completo en Supabase alojado (ETL_TEST_CUSTOMERS)

Qué es real y qué no:
    - Cliente, transacción, comercio, fecha, monto, estado y fraud_score salen de la base.
    - Lo que el cliente responde en el chat (reconoce o no, cuántos cargos, tarjeta
      robada, acepta bloqueo) es el escenario del caso, no un dato del dataset.
    - R13 necesita un reclamo abierto sobre la transacción: complaints no referencia
      transacciones, así que se declara como fixture.

Los hechos usan la forma de `Facts` de backend/src/rules/engine.ts, para que el
arnés de evaluación pueda llamar decide(hechos) y comparar con `esperado`.

Uso (misma conexión que etl.py):
    DB_PORT=55432 python generar_casos.py
"""
import json
import os
import unicodedata
from datetime import date, timedelta
from typing import Literal, Optional

import psycopg
from pydantic import BaseModel, ConfigDict

from etl import CORTE, url_base_datos

FECHA_REFERENCIA = CORTE.date()  # "hoy" para el agente: el dataset termina aquí
DIR_SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "casos_prueba")

# Umbrales de rules.json (hoja Umbrales de la matriz)
VENTANA_DIAS = 120
TOLERANCIA_DIAS = 1
SCORE_BLOQUEO = 30
CARGOS_PARA_FRAUDE = 2
MAX_ACLARACIONES = 2

CASOS_POR_REGLA = 20
CASOS_POR_VARIANTE_BUSQUEDA = 12
CASOS_POR_BORDE = 5

# Derivación esperada por regla (columnas "Derivación" y "Cola" de la matriz)
COLA = {
    "R12": "Asesor reclamos",
    "R18": "Analista de fraude",
    "R19": "Analista de fraude",
    "R20": "Back office disputas",
}

# Compras con comercio, en tarjetas activas del propio cliente: lo que se puede disputar y bloquear
BASE = """
    SELECT t.transaction_id, t.customer_id, t.product_id, t.transaction_date::date AS fecha,
           t.amount, t.currency, t.monto_usd, t.merchant_name, t.transaction_status,
           t.fraud_score, t.is_fraud, (%(corte)s::date - t.transaction_date::date) AS edad_dias
    FROM {esquema}.transactions t
    JOIN {esquema}.products p ON p.product_id = t.product_id AND p.customer_id = t.customer_id
    WHERE t.transaction_type = 'Purchase'
      AND t.merchant_name IS NOT NULL
      AND p.product_type IN ('Tarjeta Crédito', 'Tarjeta Débito')
      AND p.product_status = 'Active'
      AND t.transaction_date::date <= %(corte)s::date
"""
EN_VENTANA = f"edad_dias BETWEEN 0 AND {VENTANA_DIAS}"
SCORE_BAJO = f"fraud_score <= {SCORE_BLOQUEO}"


# ----------------------------------------------------------------------------
# Esquema del archivo de casos
# ----------------------------------------------------------------------------
class Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Consulta(Estricto):
    """Lo que el cliente describe; entrada de txn.buscar."""
    fecha_desde: date
    fecha_hasta: date
    monto: Optional[float] = None
    moneda: Optional[str] = None
    comercio: Optional[str] = None


class Esperado(Estricto):
    regla: Optional[str] = None            # None en los casos de solo búsqueda
    deriva: Optional[bool] = None
    cola: Optional[str] = None
    prioridad: Optional[Literal["normal", "alta"]] = None
    transaccion_objetivo: Optional[str] = None       # búsqueda: debe quedar en el top 3
    transacciones_candidatas: Optional[list[str]] = None  # R11: las que se deben ofrecer


class Caso(Estricto):
    id: str
    grupo: Literal["decision", "busqueda", "borde"]
    variante: str
    origen: Literal["real", "real + fixture de reclamo"]
    customer_id: str
    transaction_ids: list[str]
    consulta: Optional[Consulta] = None
    hechos: Optional[dict] = None
    esperado: Esperado
    es_fraude_real: Optional[bool] = None  # is_fraud de la transacción ancla (verdad del dataset)
    nota: Optional[str] = None


# ----------------------------------------------------------------------------
# Selección determinista
# ----------------------------------------------------------------------------
class Selector:
    def __init__(self, conn, esquema):
        self.conn = conn
        self.base = BASE.format(esquema=esquema)
        self.esquema = esquema
        self.usados = set()  # un cliente aparece en un solo caso

    def filas(self, sql, **params):
        cur = self.conn.execute(sql, {"corte": FECHA_REFERENCIA, **params})
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, f)) for f in cur.fetchall()]

    def anclas(self, condicion, n, orden="md5(transaction_id)"):
        """n transacciones que cumplen la condición, de clientes aún no usados."""
        candidatas = self.filas(
            f"SELECT * FROM ({self.base}) b WHERE {condicion} ORDER BY {orden}, transaction_id LIMIT %(lim)s",
            lim=n * 20 + len(self.usados))
        elegidas = []
        for f in candidatas:
            if f["customer_id"] not in self.usados:
                self.usados.add(f["customer_id"])
                elegidas.append(f)
                if len(elegidas) == n:
                    break
        return elegidas

    def fechas_con_movimiento(self, customer_id):
        return {f["fecha"] for f in self.filas(
            f"SELECT DISTINCT transaction_date::date AS fecha FROM {self.esquema}.transactions "
            "WHERE customer_id = %(c)s", c=customer_id)}

    def compras_en_rango(self, customer_id, comercio, desde, hasta):
        return self.filas(
            f"SELECT * FROM ({self.base}) b WHERE customer_id = %(c)s AND merchant_name = %(m)s "
            "AND fecha BETWEEN %(d)s AND %(h)s ORDER BY fecha, transaction_id",
            c=customer_id, m=comercio, d=desde, h=hasta)


# ----------------------------------------------------------------------------
# Construcción de hechos (forma de Facts en engine.ts)
# ----------------------------------------------------------------------------
def hechos_base():
    return {
        "session": {"valid": True, "otpFailures": 0, "expiredMidFlow": False},
        "message": {"injectionAttempt": False, "asksForHuman": False},
        "intent": {"label": "cargo_no_reconocido", "confidence": 0.95, "clarificationsAsked": 0},
    }


def hechos_busqueda(candidatas=1, seleccionada=True, ajena=False, aclaraciones=0):
    return {"referencesForeignTransaction": ajena, "candidates": candidatas,
            "selected": seleccionada, "clarificationsAsked": aclaraciones}


def hechos_transaccion(tx, reclamo_abierto=False):
    return {
        "status": tx["transaction_status"],
        "ageDays": tx["edad_dias"],
        "fraudScore": tx["fraud_score"],
        "amountUsd": float(tx["monto_usd"]),
        "kind": "compra",
        "hasOpenDispute": reclamo_abierto,
    }


def hechos_cliente(reconoce, cargos=1, robada=False, acepta_bloqueo=None):
    h = {"recognizesCharge": reconoce, "unrecognizedCharges": cargos,
         "cardLostOrStolen": robada, "autoReversalsInPeriod": 0}
    if acepta_bloqueo is not None:
        h["acceptsBlock"] = acepta_bloqueo
    return h


def consulta_exacta(tx, dias=0, comercio=True, monto=True):
    f = tx["fecha"] + timedelta(days=dias)
    return Consulta(fecha_desde=f, fecha_hasta=f,
                    monto=float(tx["amount"]) if monto else None,
                    moneda=tx["currency"] if monto else None,
                    comercio=tx["merchant_name"] if comercio else None)


def con_errata(texto):
    """Comercio como lo escribiría el cliente: sin acentos, en minúscula y sin una letra."""
    plano = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").lower()
    return plano[:2] + plano[3:]


def esperado_regla(regla, prioridad=None, deriva=None):
    deriva = regla in COLA if deriva is None else deriva
    return Esperado(regla=regla, deriva=deriva, cola=COLA.get(regla) if deriva else None,
                    prioridad=(prioridad or "normal") if deriva else None)


def caso_decision(regla, n, tx, variante, cliente=None, reclamo_abierto=False, grupo="decision",
                  prioridad=None, nota=None, extra_ids=()):
    h = hechos_base()
    h["search"] = hechos_busqueda()
    h["transaction"] = hechos_transaccion(tx, reclamo_abierto)
    if cliente:
        h["customer"] = cliente
    prefijo = "D08-BORDE" if grupo == "borde" else f"D08-{regla}"
    return Caso(
        id=f"{prefijo}-{variante}-{n:03d}" if grupo == "borde" else f"{prefijo}-{n:03d}",
        grupo=grupo, variante=variante,
        origen="real + fixture de reclamo" if reclamo_abierto else "real",
        customer_id=tx["customer_id"], transaction_ids=[tx["transaction_id"], *extra_ids],
        consulta=consulta_exacta(tx), hechos=h, esperado=esperado_regla(regla, prioridad),
        es_fraude_real=tx["is_fraud"], nota=nota)


# ----------------------------------------------------------------------------
# Casos por regla
# ----------------------------------------------------------------------------
def casos_identificar(s):
    casos = []

    # R09: el cliente de la sesión nombra una transacción real de otra persona
    pares = s.anclas(f"{EN_VENTANA} AND transaction_status = 'Approved'", CASOS_POR_REGLA * 2)
    for n, (propio, ajeno) in enumerate(zip(pares[::2], pares[1::2]), 1):
        h = hechos_base()
        h["search"] = hechos_busqueda(candidatas=0, seleccionada=False, ajena=True)
        casos.append(Caso(
            id=f"D08-R09-{n:03d}", grupo="decision", variante="transaccion_de_otro_cliente", origen="real",
            customer_id=propio["customer_id"], transaction_ids=[ajeno["transaction_id"]],
            hechos=h, esperado=esperado_regla("R09"),
            nota=f"La transacción pertenece a {ajeno['customer_id']}; no se debe confirmar ni negar su existencia."))

    # R10: el cliente describe una fecha en la que no tiene ningún movimiento (+/- 1 día)
    for n, tx in enumerate(s.anclas(f"{EN_VENTANA} AND transaction_status = 'Approved'", CASOS_POR_REGLA), 1):
        ocupadas = s.fechas_con_movimiento(tx["customer_id"])
        libre = next(d for d in (tx["fecha"] - timedelta(days=k) for k in range(3, VENTANA_DIAS))
                     if not any(d + timedelta(days=j) in ocupadas
                                for j in range(-TOLERANCIA_DIAS, TOLERANCIA_DIAS + 1)))
        agotado = n > CASOS_POR_REGLA // 2  # la mitad ya pidió el máximo de aclaraciones
        h = hechos_base()
        h["search"] = hechos_busqueda(candidatas=0, seleccionada=False,
                                      aclaraciones=MAX_ACLARACIONES if agotado else 0)
        casos.append(Caso(
            id=f"D08-R10-{n:03d}", grupo="decision",
            variante="sin_candidatas_tras_aclarar" if agotado else "sin_candidatas", origen="real",
            customer_id=tx["customer_id"], transaction_ids=[],
            consulta=Consulta(fecha_desde=libre, fecha_hasta=libre, monto=float(tx["amount"]),
                              moneda=tx["currency"], comercio=tx["merchant_name"]),
            hechos=h,
            esperado=Esperado(regla="R10", deriva=agotado, cola="Asesor reclamos" if agotado else None,
                              prioridad="normal" if agotado else None),
            nota="Cliente real; en la fecha descrita (+/- 1 día) no tiene ningún movimiento."))

    # R11: dos o más compras reales al mismo comercio en la misma semana
    repetidas = s.anclas(
        f"""{EN_VENTANA} AND transaction_status = 'Approved' AND EXISTS (
              SELECT 1 FROM ({s.base}) o
              WHERE o.customer_id = b.customer_id AND o.merchant_name = b.merchant_name
                AND o.transaction_id <> b.transaction_id
                AND o.fecha BETWEEN b.fecha AND b.fecha + 6)""", CASOS_POR_REGLA)
    for n, tx in enumerate(repetidas, 1):
        desde, hasta = tx["fecha"], tx["fecha"] + timedelta(days=6)
        grupo = s.compras_en_rango(tx["customer_id"], tx["merchant_name"],
                                   desde - timedelta(days=TOLERANCIA_DIAS), hasta + timedelta(days=TOLERANCIA_DIAS))
        ids = [g["transaction_id"] for g in grupo]
        h = hechos_base()
        h["search"] = hechos_busqueda(candidatas=len(ids), seleccionada=False)
        casos.append(Caso(
            id=f"D08-R11-{n:03d}", grupo="decision", variante="mismo_comercio_misma_semana", origen="real",
            customer_id=tx["customer_id"], transaction_ids=ids,
            consulta=Consulta(fecha_desde=desde, fecha_hasta=hasta, comercio=tx["merchant_name"]),
            hechos=h, esperado=Esperado(regla="R11", deriva=False, transacciones_candidatas=ids)))

    # R12: compra real fuera del plazo de 120 días
    for n, tx in enumerate(s.anclas(f"edad_dias BETWEEN {VENTANA_DIAS + 30} AND 365 "
                                    "AND transaction_status = 'Approved'", CASOS_POR_REGLA), 1):
        casos.append(caso_decision("R12", n, tx, "fuera_de_plazo"))

    # R13: transacción real con un reclamo abierto (fixture declarado)
    for n, tx in enumerate(s.anclas(f"{EN_VENTANA} AND transaction_status = 'Approved' AND {SCORE_BAJO}",
                                    CASOS_POR_REGLA), 1):
        casos.append(caso_decision("R13", n, tx, "reclamo_ya_abierto", reclamo_abierto=True,
                                   nota="El reclamo abierto es un fixture: complaints no referencia transacciones."))

    # R14, R15, R16: estados reales que cierran el caso sin reclamo
    for regla, estado, extra in [("R14", "Declined", ""),
                                 ("R15", "Pending", f" AND (fraud_score IS NULL OR {SCORE_BAJO})"),
                                 ("R16", "Reversed", "")]:
        for n, tx in enumerate(s.anclas(f"{EN_VENTANA} AND transaction_status = '{estado}'{extra}",
                                        CASOS_POR_REGLA), 1):
            casos.append(caso_decision(regla, n, tx, f"estado_{estado.lower()}"))
    return casos


def casos_decidir(s):
    casos = []
    aprobada = f"{EN_VENTANA} AND transaction_status = 'Approved'"

    # R17: el cliente ve el detalle y reconoce el cargo
    for n, tx in enumerate(s.anclas(f"{aprobada} AND {SCORE_BAJO}", CASOS_POR_REGLA), 1):
        casos.append(caso_decision("R17", n, tx, "reconoce_tras_detalle", cliente=hechos_cliente(True)))

    # R18: no reconoce y el fraud_score real supera el umbral -> bloqueo automático
    for n, tx in enumerate(s.anclas(f"{aprobada} AND fraud_score > {SCORE_BLOQUEO}", CASOS_POR_REGLA), 1):
        casos.append(caso_decision("R18", n, tx, "score_alto", cliente=hechos_cliente(False), prioridad="alta"))

    # R19: score bajo, pero el cliente reporta 2 cargos reales o la tarjeta robada
    mitad = CASOS_POR_REGLA // 2
    dobles = s.anclas(
        f"""{aprobada} AND {SCORE_BAJO} AND EXISTS (
              SELECT 1 FROM ({s.base}) o
              WHERE o.customer_id = b.customer_id AND o.product_id = b.product_id
                AND o.transaction_id <> b.transaction_id AND o.transaction_status = 'Approved'
                AND o.fraud_score <= {SCORE_BLOQUEO} AND o.edad_dias BETWEEN 0 AND {VENTANA_DIAS})""", mitad)
    for n, tx in enumerate(dobles, 1):
        otra = s.filas(
            f"""SELECT transaction_id FROM ({s.base}) o
                WHERE o.customer_id = %(c)s AND o.product_id = %(p)s AND o.transaction_id <> %(t)s
                  AND o.transaction_status = 'Approved' AND o.fraud_score <= {SCORE_BLOQUEO}
                  AND o.edad_dias BETWEEN 0 AND {VENTANA_DIAS}
                ORDER BY abs(o.fecha - %(f)s), o.transaction_id LIMIT 1""",
            c=tx["customer_id"], p=tx["product_id"], t=tx["transaction_id"], f=tx["fecha"])[0]["transaction_id"]
        casos.append(caso_decision(
            "R19", n, tx, "dos_cargos_no_reconocidos", extra_ids=[otra],
            cliente=hechos_cliente(False, cargos=CARGOS_PARA_FRAUDE, acepta_bloqueo=n % 2 == 0)))
    for n, tx in enumerate(s.anclas(f"{aprobada} AND {SCORE_BAJO}", CASOS_POR_REGLA - mitad), mitad + 1):
        casos.append(caso_decision(
            "R19", n, tx, "tarjeta_perdida_o_robada",
            cliente=hechos_cliente(False, robada=True, acepta_bloqueo=n % 2 == 0)))

    # R20: no reconoce, score bajo y un solo cargo -> disputa
    for n, tx in enumerate(s.anclas(f"{aprobada} AND {SCORE_BAJO}", CASOS_POR_REGLA), 1):
        casos.append(caso_decision("R20", n, tx, "un_cargo_score_bajo",
                                   cliente=hechos_cliente(False, acepta_bloqueo=n % 4 == 0)))
    return casos


def casos_borde(s):
    """Límites exactos de los umbrales, sobre transacciones reales."""
    casos = []
    aprobada = "transaction_status = 'Approved'"
    bordes = [
        ("score_igual_30", "R20", f"{EN_VENTANA} AND {aprobada} AND fraud_score = {SCORE_BLOQUEO}",
         "md5(transaction_id)", None, "30 exacto no supera el umbral (estrictamente mayor que)."),
        ("score_apenas_sobre_30", "R18", f"{EN_VENTANA} AND {aprobada} AND fraud_score > {SCORE_BLOQUEO}",
         "fraud_score", "alta", "Los scores reales más bajos por encima del umbral."),
        ("score_nulo", "R20", f"{EN_VENTANA} AND {aprobada} AND fraud_score IS NULL",
         "md5(transaction_id)", None,
         "SUPUESTO A CONFIRMAR: fraud_score nulo se trata como riesgo no alto (en el motor, null > 30 es falso)."),
        ("edad_120_dias", "R20", f"edad_dias = {VENTANA_DIAS} AND {aprobada} AND {SCORE_BAJO}",
         "md5(transaction_id)", None, "120 días exactos sigue dentro del plazo."),
        ("edad_121_dias", "R12", f"edad_dias = {VENTANA_DIAS + 1} AND {aprobada}",
         "md5(transaction_id)", None, "Un día fuera del plazo."),
    ]
    for variante, regla, condicion, orden, prioridad, nota in bordes:
        for n, tx in enumerate(s.anclas(condicion, CASOS_POR_BORDE, orden), 1):
            cliente = None if regla == "R12" else hechos_cliente(False)
            casos.append(caso_decision(regla, n, tx, variante, cliente=cliente, grupo="borde",
                                       prioridad=prioridad, nota=nota))
    return casos


def casos_busqueda(s):
    """Para txn.buscar (M07): la transacción objetivo debe quedar en el top 3."""
    variantes = [
        ("exacta", lambda tx: consulta_exacta(tx)),
        ("fecha_un_dia_despues", lambda tx: consulta_exacta(tx, dias=1)),
        ("fecha_un_dia_antes", lambda tx: consulta_exacta(tx, dias=-1)),
        ("comercio_mal_escrito", lambda tx: consulta_exacta(tx).model_copy(
            update={"comercio": con_errata(tx["merchant_name"])})),
        ("solo_fecha_y_monto", lambda tx: consulta_exacta(tx, comercio=False)),
    ]
    casos = []
    for variante, construir in variantes:
        for n, tx in enumerate(s.anclas(f"{EN_VENTANA} AND transaction_status = 'Approved'",
                                        CASOS_POR_VARIANTE_BUSQUEDA), 1):
            casos.append(Caso(
                id=f"D08-BUSQ-{variante}-{n:03d}", grupo="busqueda", variante=variante, origen="real",
                customer_id=tx["customer_id"], transaction_ids=[tx["transaction_id"]],
                consulta=construir(tx), esperado=Esperado(transaccion_objetivo=tx["transaction_id"]),
                es_fraude_real=tx["is_fraud"]))
    return casos


def generar(conn, esquema):
    s = Selector(conn, esquema)
    # Primero las reglas con pocas transacciones disponibles, para que no se queden sin clientes
    casos = casos_borde(s) + casos_decidir(s) + casos_identificar(s) + casos_busqueda(s)
    return sorted(casos, key=lambda c: c.id)


def main():
    esquema = os.getenv("DB_SCHEMA", "bank")
    with psycopg.connect(url_base_datos()) as conn:
        casos = generar(conn, esquema)

    conteo = {}
    for c in casos:
        clave = c.esperado.regla or "busqueda"
        conteo[clave] = conteo.get(clave, 0) + 1
    documento = {
        "meta": {
            "tarea": "D08",
            "generado_por": "data_pipeline/generar_casos.py",
            "fuente": "esquema bank cargado por data_pipeline/etl.py (carga completa)",
            "fecha_referencia": FECHA_REFERENCIA.isoformat(),
            "umbrales": {"searchWindowDays": VENTANA_DIAS, "dateToleranceDays": TOLERANCIA_DIAS,
                         "fraudScoreAutoBlock": SCORE_BLOQUEO,
                         "unrecognizedChargesForFraud": CARGOS_PARA_FRAUDE,
                         "maxClarifications": MAX_ACLARACIONES},
            "casos_por_regla": dict(sorted(conteo.items())),
        },
        "casos": [c.model_dump(mode="json", exclude_none=True) for c in casos],
    }

    os.makedirs(DIR_SALIDA, exist_ok=True)
    with open(os.path.join(DIR_SALIDA, "casos_r09_r20.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(documento, f, ensure_ascii=False, indent=2)
        f.write("\n")
    clientes = sorted({c.customer_id for c in casos})
    with open(os.path.join(DIR_SALIDA, "clientes_prueba.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(clientes) + "\n")

    print(f"{len(casos)} casos, {len(clientes)} clientes de prueba -> {DIR_SALIDA}")
    for regla, n in sorted(conteo.items()):
        print(f"  {regla:9s} {n}")


if __name__ == "__main__":
    main()

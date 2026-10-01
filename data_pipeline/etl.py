"""ETL idempotente: CSV crudos de S3 -> limpieza -> PostgreSQL (y Parquet opcional).

Cada tabla se recarga dentro de una sola transacción (CREATE IF NOT EXISTS +
TRUNCATE + COPY + verificación de conteo), así que correrlo dos veces deja la
base igual y un fallo a mitad de camino no deja nada a medias.

Variables de entorno:
    ETL_INPUT_DIR     carpeta con los CSV crudos (default: ./tablas_amazon)
    ETL_WINDOW_DAYS   si se define, las tablas de hechos solo cargan las particiones
                      de los últimos N días antes del corte (120 para Supabase alojado)
    ETL_OUTPUT_DIR    si se define, además exporta los datos limpios a Parquet
    DATABASE_URL      conexión completa (Supabase alojado); si no existe se arma con
                      DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
    DB_SCHEMA         esquema destino (default: bank)

Uso:
    python etl.py                     # carga completa
    python etl.py --window-days 120   # ventana para Supabase alojado
    python etl.py --dry-run           # limpia y cuenta, sin tocar la base
"""
import argparse
import glob
import io
import os
import re
import sys
from datetime import timedelta

import pandas as pd

CORTE = pd.Timestamp("2026-06-17")  # fin del rango documentado del dataset
ARCHIVOS_POR_LOTE = 60  # particiones diarias que se leen juntas en las tablas de hechos

# Tasa implícita amount/amount_usd observada en los datos: constante por moneda (±0,1%).
TASA_USD = {"USD": 1.0, "COP": 4000.0, "ARS": 350.0}

# Especificación por tabla. Las columnas no listadas en ts/date/int/num/float/bool son text.
#   origen: ruta relativa a ETL_INPUT_DIR; con ** es una tabla de hechos particionada por día.
#   drop:   columnas que se eliminan (decisiones documentadas en el notebook, fase 4).
#   extra:  columnas que agrega la limpieza, con su tipo.
TABLAS = {
    "customers": dict(
        origen="customers.csv",
        pk="customer_id",
        drop=["registration_branch_id"],  # 100% huérfano contra branches
        ts=["registration_date", "last_updated"],
        date=["date_of_birth"],
        int=["credit_score"],
        num=["estimated_monthly_income"],
        bool=["accepts_marketing"],
        indices=[["document_number"]],
    ),
    "branches": dict(
        origen="branches/branches.csv",
        pk="branch_id",
        drop=["latitude", "longitude"],  # coordenadas inválidas
        date=["branch_opening_date"],
        int=["atm_count", "teller_window_count"],
        bool=["has_atms", "has_teller_windows"],
    ),
    "products": dict(
        origen="products.csv",
        pk="product_id",
        ts=["last_transaction_date", "last_updated"],
        date=["opening_date", "expiration_date"],
        int=["days_past_due"],
        num=["current_balance", "credit_limit"],
        float=["interest_rate"],
        bool=["has_linked_app"],
        indices=[["customer_id"], ["product_number"]],
    ),
    "transactions": dict(
        origen="transactions/**/*.csv",
        pk="transaction_id",
        drop=["latitude", "longitude", "merchant_category"],  # inválidas / duplicado de transaction_category
        ts=["transaction_date"],
        date=["process_date"],
        num=["amount", "amount_usd"],
        float=["fraud_score"],
        bool=["is_fraud"],
        extra={
            "monto_usd": "num",
            "flag_monto_usd_imputado": "bool",
            "flag_tx_antes_registro": "bool",
            "flag_tx_antes_apertura": "bool",
        },
        indices=[["customer_id", "transaction_date"], ["product_id"]],
    ),
    "call_center_interactions": dict(
        origen="call_center_interactions/**/*.csv",
        pk="interaction_id",
        drop=["contact_reason"],  # duplicado exacto de reason_category
        ts=["interaction_date"],
        date=["process_date"],
        int=["duration_seconds", "wait_time_seconds"],
        float=["sentiment_score"],
        bool=["was_resolved", "requires_followup", "was_escalated", "has_transcript", "has_recording"],
        indices=[["customer_id", "interaction_date"]],
    ),
    "call_transcripts": dict(
        origen="call_transcripts/**/*.csv",
        pk="transcript_id",
        date=["process_date"],
        int=["duration_seconds"],
        float=["accent_confidence"],
        indices=[["interaction_id"], ["customer_id"]],
    ),
    "complaints": dict(
        origen="complaints/**/*.csv",
        pk="complaint_id",
        drop=["origin_interaction_id"],  # 100% nula
        ts=["creation_date", "assignment_date", "first_response_date", "resolution_date", "closing_date"],
        date=["process_date"],
        int=["resolution_days", "resolution_satisfaction"],
        num=["claimed_amount", "compensation_granted"],
        bool=["sla_breached", "is_repeat_complainer"],
        indices=[["customer_id"], ["affected_product_id"]],
    ),
}

COLS_ACENTO = ["detected_accent", "customer_detected_accent", "agent_used_accent"]
TIPO_PG = {"ts": "timestamp", "date": "date", "int": "bigint", "num": "numeric",
           "float": "double precision", "bool": "boolean"}


# ----------------------------------------------------------------------------
# Lectura
# ----------------------------------------------------------------------------
def listar_archivos(ruta_base, tabla, ventana_dias=None):
    """Archivos de la tabla en orden determinista; con ventana, solo particiones recientes."""
    patron = os.path.join(ruta_base, TABLAS[tabla]["origen"])
    archivos = sorted(glob.glob(patron, recursive=True))
    if not archivos:
        raise FileNotFoundError(f"No hay archivos para '{tabla}' en {patron}")
    if ventana_dias is None or "**" not in patron:
        return archivos
    desde = CORTE - timedelta(days=ventana_dias)
    return [f for f in archivos if _fecha_particion(f) >= desde]


def _fecha_particion(ruta):
    m = re.search(r"year=(\d{4})[\\/]month=(\d{2})[\\/]day=(\d{2})", ruta)
    if not m:
        raise ValueError(f"Ruta sin partición year=/month=/day=: {ruta}")
    return pd.Timestamp(year=int(m[1]), month=int(m[2]), day=int(m[3]))


def leer_csv(archivos):
    return pd.concat((pd.read_csv(f, low_memory=False) for f in archivos), ignore_index=True)


def lotes(archivos, n=ARCHIVOS_POR_LOTE):
    for i in range(0, len(archivos), n):
        yield archivos[i:i + n]


# ----------------------------------------------------------------------------
# Limpieza
# ----------------------------------------------------------------------------
def columnas_destino(tabla, columnas_origen):
    """Columnas finales (nombre, tipo lógico) a partir del encabezado del CSV."""
    spec = TABLAS[tabla]
    tipos = {c: k for k in TIPO_PG for c in spec.get(k, [])}
    cols = [(c, tipos.get(c, "text")) for c in columnas_origen if c not in spec.get("drop", [])]
    return cols + list(spec.get("extra", {}).items())


def tipar(df, tabla):
    """Reglas comunes: drop de columnas, acentos nulos -> 'neutral' y tipos nativos."""
    spec = TABLAS[tabla]
    df = df.drop(columns=spec.get("drop", []), errors="ignore")
    for c in COLS_ACENTO:
        if c in df.columns:
            df[c] = df[c].fillna("neutral")
    for c in spec.get("ts", []) + spec.get("date", []):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in spec.get("int", []):
        df[c] = df[c].astype("Int64")
    for c in spec.get("bool", []):
        df[c] = df[c].astype("boolean")
    return df


def limpiar_products(df):
    df = tipar(df, "products")
    # product_number repetido: se rompe la colisión con un sufijo estable (índice de la fila)
    df["product_number"] = df["product_number"].astype(str)
    dup = df.duplicated(subset=["product_number"], keep="first")
    df.loc[dup, "product_number"] = df.loc[dup, "product_number"] + "-DUP" + df.index[dup].astype(str)
    return df


def limpiar_transactions(df, fecha_registro, fecha_apertura):
    df = tipar(df, "transactions")
    df["transaction_country"] = df["transaction_country"].replace({"Mexico": "México"})
    df["response_code"] = df["response_code"].astype("Int64").astype("string")  # 14.0 -> "14"

    # amount_usd viene vacío en todo USD y en ~5% de COP/ARS: se completa con la tasa implícita
    df["flag_monto_usd_imputado"] = df["amount_usd"].isna()
    df["monto_usd"] = df["amount_usd"].fillna(df["amount"] / df["currency"].map(TASA_USD)).round(2)

    # Desfases temporales: se marcan, no se eliminan
    df["flag_tx_antes_registro"] = df["transaction_date"] < df["customer_id"].map(fecha_registro)
    df["flag_tx_antes_apertura"] = df["transaction_date"] < df["product_id"].map(fecha_apertura)
    return df


def limpiar(df, tabla, fecha_registro=None, fecha_apertura=None):
    if tabla == "products":
        return limpiar_products(df)
    if tabla == "transactions":
        return limpiar_transactions(df, fecha_registro, fecha_apertura)
    return tipar(df, tabla)


# ----------------------------------------------------------------------------
# Carga a PostgreSQL
# ----------------------------------------------------------------------------
def url_base_datos():
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    return (f"host={os.getenv('DB_HOST', 'localhost')} port={os.getenv('DB_PORT', '5432')} "
            f"user={os.getenv('DB_USER', 'postgres')} password={os.getenv('DB_PASSWORD', 'postgres')} "
            f"dbname={os.getenv('DB_NAME', 'postgres')}")


def crear_tabla(cur, esquema, tabla, cols):
    spec = TABLAS[tabla]
    ddl = ", ".join(f'"{c}" {TIPO_PG.get(k, "text")}' for c, k in cols)
    cur.execute(f'CREATE TABLE IF NOT EXISTS {esquema}."{tabla}" ({ddl}, PRIMARY KEY ("{spec["pk"]}"))')
    for idx in spec.get("indices", []):
        nombre = f'{tabla}_{"_".join(idx)}_idx'
        cur.execute(f'CREATE INDEX IF NOT EXISTS "{nombre}" ON {esquema}."{tabla}" '
                    f'({", ".join(chr(34) + c + chr(34) for c in idx)})')


def copiar(cur, esquema, tabla, df, cols):
    nombres = [c for c, _ in cols]
    buf = io.StringIO()
    df[nombres].to_csv(buf, index=False, header=False, lineterminator="\n")
    lista = ", ".join(f'"{c}"' for c in nombres)
    with cur.copy(f'COPY {esquema}."{tabla}" ({lista}) FROM STDIN WITH (FORMAT csv)') as copy:
        copy.write(buf.getvalue())


def exportar_parquet(df, directorio, tabla, parte):
    destino = os.path.join(directorio, tabla)
    os.makedirs(destino, exist_ok=True)
    df.to_parquet(os.path.join(destino, f"part-{parte:04d}.parquet"), index=False)


def procesar_tabla(tabla, ruta_base, ventana_dias, conn, esquema, dir_parquet, contexto):
    """Lee, limpia y carga una tabla. Devuelve (filas de origen, filas en destino)."""
    archivos = listar_archivos(ruta_base, tabla, ventana_dias)
    cols = columnas_destino(tabla, pd.read_csv(archivos[0], nrows=0).columns)
    es_hecho = "**" in TABLAS[tabla]["origen"]
    filas_origen = 0

    cur = conn.cursor() if conn else None
    if cur:
        crear_tabla(cur, esquema, tabla, cols)
        cur.execute(f'TRUNCATE {esquema}."{tabla}"')

    for parte, lote in enumerate(lotes(archivos) if es_hecho else [archivos]):
        crudo = leer_csv(lote)
        filas_origen += len(crudo)
        df = limpiar(crudo, tabla, contexto.get("fecha_registro"), contexto.get("fecha_apertura"))
        if tabla == "customers":
            contexto["fecha_registro"] = df.set_index("customer_id")["registration_date"]
        if tabla == "products":
            contexto["fecha_apertura"] = df.set_index("product_id")["opening_date"]
        if cur:
            copiar(cur, esquema, tabla, df, cols)
        if dir_parquet:
            exportar_parquet(df, dir_parquet, tabla, parte)

    filas_destino = filas_origen
    if cur:
        cur.execute(f'SELECT count(*) FROM {esquema}."{tabla}"')
        filas_destino = cur.fetchone()[0]
        if filas_destino != filas_origen:
            raise RuntimeError(f"{tabla}: origen {filas_origen:,} != destino {filas_destino:,}")
        conn.commit()
    print(f"{tabla:26s} archivos={len(archivos):>5,}  origen={filas_origen:>10,}  destino={filas_destino:>10,}")
    return filas_origen, filas_destino


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--window-days", type=int,
                        default=int(os.environ["ETL_WINDOW_DAYS"]) if os.getenv("ETL_WINDOW_DAYS") else None)
    parser.add_argument("--dry-run", action="store_true", help="limpia y cuenta, sin tocar la base")
    args = parser.parse_args()

    ruta_base = os.getenv("ETL_INPUT_DIR", "./tablas_amazon")
    esquema = os.getenv("DB_SCHEMA", "bank")
    dir_parquet = os.getenv("ETL_OUTPUT_DIR")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", esquema):
        sys.exit(f"DB_SCHEMA inválido: {esquema!r}")

    alcance = f"ventana de {args.window_days} días" if args.window_days else "carga completa"
    print(f"ETL | origen={ruta_base} | {alcance} | destino={'dry-run' if args.dry_run else esquema}")

    conn = None
    if not args.dry_run:
        import psycopg
        conn = psycopg.connect(url_base_datos())
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {esquema}")
        conn.commit()

    try:
        contexto = {}
        # dimensiones primero: transactions necesita las fechas de registro y apertura
        for tabla in TABLAS:
            procesar_tabla(tabla, ruta_base, args.window_days, conn, esquema, dir_parquet, contexto)
    finally:
        if conn:
            conn.close()
    print("ETL finalizado: los conteos por tabla coinciden con el origen.")


if __name__ == "__main__":
    main()

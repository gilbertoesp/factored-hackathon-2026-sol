"""Subtipo de un `cobro_indebido` a partir de los hechos de la transacción elegida.

  duplicado  otra transacción del mismo cliente con igual monto, moneda y comercio dentro de DUP_WINDOW_MIN minutos
             (ambas no rechazadas ni revertidas).
  comision   ajuste/cargo sin comercio (`transaction_type = 'Adjustment'`) o comercio con palabras de comisión.
  compra     cualquier otro cargo (compra, pago, retiro...).

Es una función pura que alimenta `kind` y `duplicateGapMinutes` del motor de reglas (R21 a R23, R29) y los fixtures de tests/fixtures/cobros_indebidos.json.
"""
import re
from datetime import timedelta

DUP_WINDOW_MIN = 10  # duplicateWindowMinutes de la matriz (R23, backend/src/rules/rules.json en feat/rules-engine)
FEE_WORDS = re.compile(r"comisi|\bfee\b|cargo por|mantenimiento|membres", re.I)
NON_EFFECTIVE = {"Declined", "Reversed"}


def detectar(selected, others=()):
    """Devuelve (subtipo, motivo). `others`: demás transacciones del mismo cliente (sin `selected`)."""
    if selected["transaction_status"] not in NON_EFFECTIVE:
        for o in others:
            if (o["transaction_id"] != selected["transaction_id"] and o["transaction_status"] not in NON_EFFECTIVE
                    and o["amount"] == selected["amount"] and o["currency"] == selected["currency"]
                    and (o.get("merchant_name") or "") == (selected.get("merchant_name") or "")
                    and abs(o["transaction_date"] - selected["transaction_date"]) <= timedelta(minutes=DUP_WINDOW_MIN)):
                return "duplicado", f"misma transacción repetida ({o['transaction_id']})"
    if selected["transaction_type"] == "Adjustment" or FEE_WORDS.search(selected.get("merchant_name") or ""):
        return "comision", "ajuste/cargo sin comercio o comercio de comisión"
    return "compra", "cargo normal"

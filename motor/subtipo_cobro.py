"""Subtipo de un `cobro_indebido` a partir de los hechos de la transacción elegida.

  duplicado  otra transacción del mismo cliente con igual monto, moneda y comercio dentro de DUP_WINDOW_H horas
             (ambas no rechazadas ni revertidas).
  comision   ajuste/cargo sin comercio (`transaction_type = 'Adjustment'`) o comercio con palabras de comisión.
  compra     cualquier otro cargo (compra, pago, retiro...).

Es una función pura: la usan las reglas R21 a R23 y los fixtures de tests/fixtures/cobros_indebidos.json.
"""
import re
from datetime import timedelta

DUP_WINDOW_H = 24
FEE_WORDS = re.compile(r"comisi|\bfee\b|cargo por|mantenimiento|membres", re.I)
NON_EFFECTIVE = {"Declined", "Reversed"}


def detectar(selected, others=()):
    """Devuelve (subtipo, motivo). `others`: demás transacciones del mismo cliente (sin `selected`)."""
    if selected["transaction_status"] not in NON_EFFECTIVE:
        for o in others:
            if (o["transaction_id"] != selected["transaction_id"] and o["transaction_status"] not in NON_EFFECTIVE
                    and o["amount"] == selected["amount"] and o["currency"] == selected["currency"]
                    and (o.get("merchant_name") or "") == (selected.get("merchant_name") or "")
                    and abs(o["transaction_date"] - selected["transaction_date"]) <= timedelta(hours=DUP_WINDOW_H)):
                return "duplicado", f"misma transacción repetida ({o['transaction_id']})"
    if selected["transaction_type"] == "Adjustment" or FEE_WORDS.search(selected.get("merchant_name") or ""):
        return "comision", "ajuste/cargo sin comercio o comercio de comisión"
    return "compra", "cargo normal"

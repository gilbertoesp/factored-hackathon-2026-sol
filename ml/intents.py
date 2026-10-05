"""Clases de intención del agente y su mapeo desde BANKING77 (M03).

Las clases son las de `Intent` en backend/src/rules/engine.ts. "ambigua" no es una
etiqueta del set de prueba: es la abstención del clasificador (R05).

BANKING77: Casanueva et al., 2020, licencia CC BY 4.0.
https://github.com/PolyAI-LDN/task-specific-datasets

El mapeo es una PROPUESTA hasta que exista la guía de etiquetado (M01).
"""

CLASES = ["cargo_no_reconocido", "cobro_indebido", "otro_reclamo", "fuera_de_alcance"]
ABSTENCION = "ambigua"
IDIOMAS = ["es", "pt", "en"]

MAPEO_BANKING77 = {
    # El cliente no reconoce el movimiento (R17 a R20)
    "cargo_no_reconocido": [
        "card_payment_not_recognised",
        "cash_withdrawal_not_recognised",
        "direct_debit_payment_not_recognised",
    ],
    # Reconoce la operación pero el cobro está mal: duplicado, comisión o cargo extra (R21 a R23, R29)
    "cobro_indebido": [
        "transaction_charged_twice",
        "extra_charge_on_statement",
        "card_payment_fee_charged",
        "cash_withdrawal_charge",
        "transfer_fee_charged",
    ],
    # Reclamo que no es una disputa de un cobro: fallas del servicio o del producto (R08)
    "otro_reclamo": [
        "card_not_working",
        "card_swallowed",
        "contactless_not_working",
        "virtual_card_not_working",
        "failed_transfer",
        "transfer_not_received_by_recipient",
        "top_up_failed",
        "balance_not_updated_after_bank_transfer",
    ],
    # Consultas y trámites que no son un reclamo (R07)
    "fuera_de_alcance": [
        "exchange_rate",
        "card_delivery_estimate",
        "change_pin",
        "activate_my_card",
        "top_up_limits",
        "lost_or_stolen_card",
        "edit_personal_details",
        "terminate_account",
        "age_limit",
        "order_physical_card",
    ],
}

# Intenciones con más de una lectura posible; quedan fuera hasta decidirlas en M01.
PENDIENTES_M01 = [
    "reverted_card_payment?",   # ¿reclamo o estado Reversed (R16)?
    "request_refund",           # ¿cobro indebido o trámite?
    "pending_card_payment",     # estado Pending (R15), no necesariamente reclamo
    "declined_card_payment",    # estado Declined (R14)
    "compromised_card",         # fraude sin transacción concreta
    "card_payment_wrong_exchange_rate",
    "wrong_exchange_rate_for_cash_withdrawal",
    "wrong_amount_of_cash_received",
    "Refund_not_showing_up",
]

CLASE_DE = {intent: clase for clase, intents in MAPEO_BANKING77.items() for intent in intents}

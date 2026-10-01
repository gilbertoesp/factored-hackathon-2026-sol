# Contrato de la API de conversación (B01)

Fuente de verdad: `backend/src/conversation/contract.ts` (zod). El chat web (F02) ya está construido contra este contrato; el adaptador de WhatsApp debe usar el mismo.

El navegador nunca llama al backend directo: habla con las rutas `/api/*` de Next.js, que reenvían dentro de la red de compose y guardan el token de sesión en una cookie httpOnly.

## 1. Sesión (OTP simulado)

`POST /api/session/otp`

```json
{ "customerRef": "CUST-000123", "language": "es" }
```

Respuesta 200:

```json
{ "challengeId": "ch_1", "destinationHint": "***1234", "demoCode": "482913" }
```

- `destinationHint` siempre enmascarado. `demoCode` solo en el demo (se muestra en pantalla porque el OTP es simulado).
- No devuelve ningún dato del cliente (R01).

`POST /api/session/verify`

```json
{ "challengeId": "ch_1", "code": "482913" }
```

- 200: `{ "sessionToken": "...", "expiresAt": "2026-10-02T15:00:00-05:00" }`
- 401: `{ "status": "invalid_code" | "blocked", "attemptsLeft": 2, "message": "..." }`. Con `blocked` (3 intentos, R02) el chat deja de pedir código y muestra `message`.

## 2. Mensajes

`POST /api/conversation/messages` con `Authorization: Bearer <sessionToken>`

Un turno lleva **uno** de: `text`, `selection` o `confirmation`.

```json
{ "conversationId": "conv_1", "language": "es", "text": "no reconozco un cobro del martes" }
{ "conversationId": "conv_1", "language": "es", "selection": { "transactionId": "TXN-9001" } }
{ "conversationId": "conv_1", "language": "es", "confirmation": { "field": "recognizesCharge", "value": false } }
```

- El primer mensaje va sin `conversationId`; la respuesta lo asigna.
- El cliente **no** puede mandar `customerId` (el esquema es estricto): sale del token.
- `selection` y `confirmation` llegan al motor como hechos verificados, sin pasar por el LLM.

Respuesta 200:

```json
{
  "conversationId": "conv_1",
  "reply": { "text": "Encontré estos movimientos. ¿Cuál es?" },
  "prompt": {
    "type": "transaction_choices",
    "options": [
      { "transactionId": "TXN-9001", "merchant": "AMAZON MKTPLACE", "date": "2026-09-29", "amount": 412000, "currency": "COP", "status": "Approved" }
    ]
  },
  "state": { "ruleId": "R11", "handoff": null, "ended": false }
}
```

| `prompt` | Cuándo | Lo que muestra el chat |
|---|---|---|
| `null` | Respuesta de texto | Solo la burbuja |
| `transaction_choices` (1 a 3 opciones) | R11 | Tarjetas para elegir, monto en moneda original |
| `confirm` con `field: "recognizesCharge"` | Antes de R17/R18-R20 | Tarjeta de la transacción + Sí / No |
| `confirm` con `field: "acceptsBlock"` | R19, R20 | Sí / No |

- `state.handoff` presente = se creó la ficha (R28); el chat muestra el número de caso.
- `state.ended = true` = el chat ofrece "Nueva consulta".

**401 en mensajes = sesión vencida (R27).** El chat vuelve al login, conserva la conversación y reenvía el mismo turno con el mismo `conversationId` después del OTP. El backend debe conservar el contexto por `conversationId` y no ejecutar ninguna acción pendiente con la sesión vencida.

## 3. Para Gilberto (B01)

- Validar el body con `messageRequest.safeParse` y devolver solo rutas de error, nunca el body (como `parseNotification`).
- Por cada turno: armar `Facts` desde la sesión + clasificador + `txn.buscar` y llamar `decide()` de `backend/src/rules/engine.ts`. Un `awaiting` se traduce en `prompt` (`search` → buscar y responder con `transaction_choices`; `customer.recognizesCharge` → `confirm`).
- `reply.text` viene de `decision.message` (rules.json) con los marcadores `[ID]`, `[SLA]`, `[comercio]` reemplazados. Para PT falta traducir los mensajes de la matriz.

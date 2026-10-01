/**
 * UI copy in the two languages the agent serves. Spanish covers MX, CO and AR;
 * Portuguese is PT-BR. Agent replies come from the backend in the customer's
 * language; this file is only the interface around them.
 */
export const LANGUAGES = ["es", "pt"] as const;
export type Language = (typeof LANGUAGES)[number];

export const copy = {
	es: {
		title: "Reclamos y cargos no reconocidos",
		subtitle: "Revisamos tus movimientos y abrimos el reclamo por ti.",
		language: "Idioma",
		loginTitle: "Confirma tu identidad",
		loginHelp: "Te enviaremos un código para continuar.",
		customerRef: "Número de cliente",
		sendCode: "Enviar código",
		codeLabel: "Código de verificación",
		codeSentTo: "Enviamos un código a",
		demoCode: "Código de prueba (solo demo):",
		verify: "Verificar",
		changeRef: "Usar otro número",
		reauth: "Por seguridad, confirma de nuevo tu identidad para continuar.",
		welcome:
			"Hola. Cuéntame qué cargo no reconoces o qué cobro crees que es incorrecto.",
		placeholder: "Escribe tu mensaje",
		send: "Enviar",
		pickOne: "Elige el movimiento:",
		yes: "Sí",
		no: "No",
		recognizeQuestion: "¿Reconoces este cargo?",
		blockQuestion: "¿Bloqueamos tu tarjeta?",
		handoff: "Tu caso pasó a un asesor. Número de caso:",
		ended: "La conversación terminó.",
		newChat: "Nueva consulta",
		error: "No pudimos procesar tu mensaje. Intenta de nuevo.",
		status: {
			Approved: "Aprobada",
			Declined: "Rechazada",
			Pending: "Pendiente",
			Reversed: "Revertida",
		},
		youSelected: "Elegí:",
	},
	pt: {
		title: "Reclamações e cobranças não reconhecidas",
		subtitle: "Verificamos suas transações e abrimos a reclamação para você.",
		language: "Idioma",
		loginTitle: "Confirme sua identidade",
		loginHelp: "Enviaremos um código para continuar.",
		customerRef: "Número de cliente",
		sendCode: "Enviar código",
		codeLabel: "Código de verificação",
		codeSentTo: "Enviamos um código para",
		demoCode: "Código de teste (somente demo):",
		verify: "Verificar",
		changeRef: "Usar outro número",
		reauth: "Por segurança, confirme sua identidade novamente para continuar.",
		welcome:
			"Olá. Conte qual cobrança você não reconhece ou qual valor acha que está errado.",
		placeholder: "Digite sua mensagem",
		send: "Enviar",
		pickOne: "Escolha a transação:",
		yes: "Sim",
		no: "Não",
		recognizeQuestion: "Você reconhece esta cobrança?",
		blockQuestion: "Bloqueamos seu cartão?",
		handoff: "Seu caso foi encaminhado a um atendente. Número do caso:",
		ended: "A conversa terminou.",
		newChat: "Nova consulta",
		error: "Não conseguimos processar sua mensagem. Tente novamente.",
		status: {
			Approved: "Aprovada",
			Declined: "Recusada",
			Pending: "Pendente",
			Reversed: "Estornada",
		},
		youSelected: "Escolhi:",
	},
} as const;

export type Copy = (typeof copy)[Language];

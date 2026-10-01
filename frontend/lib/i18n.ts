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
		welcome:
			"Hola. Cuéntame qué cargo no reconoces o qué cobro crees que es incorrecto.",
		placeholder: "Escribe tu mensaje",
		send: "Enviar",
		offline: "El chat se conectará con el agente en la siguiente versión.",
	},
	pt: {
		title: "Reclamações e cobranças não reconhecidas",
		subtitle: "Verificamos suas transações e abrimos a reclamação para você.",
		language: "Idioma",
		welcome:
			"Olá. Conte qual cobrança você não reconhece ou qual valor acha que está errado.",
		placeholder: "Digite sua mensagem",
		send: "Enviar",
		offline: "O chat será conectado ao agente na próxima versão.",
	},
} satisfies Record<Language, Record<string, string>>;

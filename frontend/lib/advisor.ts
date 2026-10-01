import "server-only";

/**
 * Server-side client for the backend's advisor API. The bearer token stays on
 * the server; the browser only receives rendered HTML.
 *
 * The Ficha type mirrors handoffTicketSchema in
 * backend/src/handoff/ticket.ts. The backend validates every ficha before
 * storing it, so this side only reads.
 */

export interface Ficha {
	caseId: string;
	createdAt: string;
	originRule: string;
	queue: string;
	priority: "normal" | "alta";
	alert: "verificacion" | null;
	language: "es" | "pt";
	channel: "web" | "whatsapp";
	customer: {
		customerId: string;
		verifiedBy: "otp";
		verifiedAt: string;
	} | null;
	request: {
		originalText: string;
		intent: string;
		intentConfidence: number;
		clarifications: string[];
	};
	transactions: {
		transactionId: string;
		merchant: string;
		date: string;
		amount: number;
		currency: string;
		amountUsd: number;
		status: "Approved" | "Declined" | "Pending" | "Reversed";
		fraudScore: number;
	}[];
	actions: {
		tool: string;
		status: "verificada" | "fallida" | "pendiente";
		reference: string | null;
		at: string;
	}[];
	pendingQuestions: string[];
	summary: string;
}

type Failure = "disabled" | "unauthorized" | "not_found" | "unreachable";

export type AdvisorResult<T> =
	| { ok: true; data: T }
	| { ok: false; reason: Failure };

async function call<T>(path: string): Promise<AdvisorResult<T>> {
	const base = process.env.BACKEND_API_URL ?? "http://localhost:4000";
	const token = process.env.ADVISOR_API_TOKEN;
	if (!token) return { ok: false, reason: "disabled" };
	let res: Response;
	try {
		res = await fetch(`${base}/api/handoff${path}`, {
			headers: { authorization: `Bearer ${token}` },
			cache: "no-store",
		});
	} catch {
		return { ok: false, reason: "unreachable" };
	}
	if (res.status === 503) return { ok: false, reason: "disabled" };
	if (res.status === 401) return { ok: false, reason: "unauthorized" };
	if (res.status === 404) return { ok: false, reason: "not_found" };
	if (!res.ok) return { ok: false, reason: "unreachable" };
	return { ok: true, data: (await res.json()) as T };
}

export function listFichas(queue?: string) {
	const qs = queue ? `?queue=${encodeURIComponent(queue)}` : "";
	return call<{ tickets: Ficha[] }>(qs);
}

export function getFicha(caseId: string) {
	return call<{ ticket: Ficha }>(`/${encodeURIComponent(caseId)}`);
}

export const REASON_TEXT: Record<Failure, string> = {
	disabled: "La vista del asesor está desactivada (falta ADVISOR_API_TOKEN).",
	unauthorized: "El backend rechazó el token del asesor.",
	not_found: "No existe una ficha con ese número de caso.",
	unreachable: "No se pudo conectar con el backend.",
};

export function formatDateTime(iso: string): string {
	return new Intl.DateTimeFormat("es-PE", {
		dateStyle: "short",
		timeStyle: "short",
		timeZone: "America/Lima",
	}).format(new Date(iso));
}

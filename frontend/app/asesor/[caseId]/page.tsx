import Link from "next/link";
import { formatDateTime, getFicha, REASON_TEXT } from "@/lib/advisor";

export const dynamic = "force-dynamic";

const ACTION_TEXT = {
	verificada: "Verificada",
	fallida: "Fallida",
	pendiente: "Pendiente: completar",
} as const;

export default async function FichaDetail({
	params,
}: {
	params: Promise<{ caseId: string }>;
}) {
	const { caseId } = await params;
	const result = await getFicha(decodeURIComponent(caseId));

	if (!result.ok) {
		return (
			<main className="shell">
				<section className="panel wide">
					<Link href="/asesor">Volver a la cola</Link>
					<p role="alert" className="notice">
						{REASON_TEXT[result.reason]}
					</p>
				</section>
			</main>
		);
	}

	const f = result.data.ticket;
	return (
		<main className="shell">
			<article className="panel wide ficha">
				<Link href="/asesor">Volver a la cola</Link>
				<header>
					<h1>Caso {f.caseId}</h1>
					<p className="muted">
						{formatDateTime(f.createdAt)} · {f.queue} · regla {f.originRule} ·{" "}
						{f.language.toUpperCase()} · {f.channel}
					</p>
					<p>
						<span className={`tag ${f.priority}`}>Prioridad {f.priority}</span>
					</p>
				</header>

				{f.alert === "verificacion" && (
					<p role="alert" className="notice">
						Alerta técnica: una acción respondió OK pero su verificación no
						coincidió. Confirma el estado real antes de informar al cliente.
					</p>
				)}

				<section>
					<h2>Resumen</h2>
					<p>{f.summary}</p>
				</section>

				<section>
					<h2>Solicitud del cliente</h2>
					<blockquote>{f.request.originalText}</blockquote>
					<p className="muted">
						Intención: {f.request.intent} (confianza{" "}
						{Math.round(f.request.intentConfidence * 100)}%)
					</p>
					{f.request.clarifications.length > 0 && (
						<ul>
							{f.request.clarifications.map((c) => (
								<li key={c}>{c}</li>
							))}
						</ul>
					)}
				</section>

				<section>
					<h2>Cliente</h2>
					{f.customer ? (
						<p>
							{f.customer.customerId}, verificado por OTP el{" "}
							{formatDateTime(f.customer.verifiedAt)}
						</p>
					) : (
						<p className="notice">
							Identidad no verificada: validar por canal seguro.
						</p>
					)}
				</section>

				<section>
					<h2>Transacciones</h2>
					{f.transactions.length === 0 ? (
						<p className="muted">Aún no se identificó la transacción.</p>
					) : (
						<div className="table-wrap">
							<table>
								<thead>
									<tr>
										<th>ID</th>
										<th>Comercio</th>
										<th>Fecha</th>
										<th>Monto</th>
										<th>USD</th>
										<th>Estado</th>
										<th>fraud_score</th>
									</tr>
								</thead>
								<tbody>
									{f.transactions.map((t) => (
										<tr key={t.transactionId}>
											<td>{t.transactionId}</td>
											<td>{t.merchant}</td>
											<td>{t.date}</td>
											<td>
												{t.amount.toLocaleString("es-PE")} {t.currency}
											</td>
											<td>{t.amountUsd.toFixed(2)}</td>
											<td>{t.status}</td>
											<td className={t.fraudScore > 30 ? "risk" : undefined}>
												{t.fraudScore}
											</td>
										</tr>
									))}
								</tbody>
							</table>
						</div>
					)}
				</section>

				<section>
					<h2>Acciones del agente</h2>
					{f.actions.length === 0 ? (
						<p className="muted">Ninguna.</p>
					) : (
						<ul>
							{f.actions.map((a) => (
								<li key={`${a.tool}-${a.at}`}>
									<strong>{a.tool}</strong>: {ACTION_TEXT[a.status]}
									{a.reference ? ` (${a.reference})` : ""},{" "}
									{formatDateTime(a.at)}
								</li>
							))}
						</ul>
					)}
				</section>

				<section>
					<h2>Preguntas pendientes</h2>
					{f.pendingQuestions.length === 0 ? (
						<p className="muted">Ninguna.</p>
					) : (
						<ul>
							{f.pendingQuestions.map((q) => (
								<li key={q}>{q}</li>
							))}
						</ul>
					)}
				</section>
			</article>
		</main>
	);
}

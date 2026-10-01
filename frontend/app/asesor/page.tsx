import Link from "next/link";
import { formatDateTime, listFichas, REASON_TEXT } from "@/lib/advisor";

export const dynamic = "force-dynamic";

export default async function AdvisorQueue({
	searchParams,
}: {
	searchParams: Promise<{ cola?: string }>;
}) {
	const { cola } = await searchParams;
	const result = await listFichas(cola);

	return (
		<main className="shell">
			<section className="panel wide">
				<header className="chat-header">
					<div>
						<h1>Fichas de derivación</h1>
						<p className="muted">
							{cola ? `Cola: ${cola}` : "Todas las colas"}, más recientes
							primero.
						</p>
					</div>
					{cola && <Link href="/asesor">Ver todas</Link>}
				</header>

				{!result.ok ? (
					<p role="alert" className="notice">
						{REASON_TEXT[result.reason]}
					</p>
				) : result.data.tickets.length === 0 ? (
					<p className="muted">No hay casos derivados.</p>
				) : (
					<div className="table-wrap">
						<table>
							<thead>
								<tr>
									<th>Caso</th>
									<th>Fecha</th>
									<th>Cola</th>
									<th>Prioridad</th>
									<th>Regla</th>
									<th>Resumen</th>
								</tr>
							</thead>
							<tbody>
								{result.data.tickets.map((t) => (
									<tr key={t.caseId}>
										<td>
											<Link href={`/asesor/${encodeURIComponent(t.caseId)}`}>
												{t.caseId}
											</Link>
										</td>
										<td>{formatDateTime(t.createdAt)}</td>
										<td>
											<Link
												href={`/asesor?cola=${encodeURIComponent(t.queue)}`}
											>
												{t.queue}
											</Link>
										</td>
										<td>
											<span className={`tag ${t.priority}`}>{t.priority}</span>
											{t.alert && <span className="tag alert">alerta</span>}
										</td>
										<td>{t.originRule}</td>
										<td>{t.summary}</td>
									</tr>
								))}
							</tbody>
						</table>
					</div>
				)}
			</section>
		</main>
	);
}

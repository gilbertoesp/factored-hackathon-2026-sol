"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";
import type {
	ConfirmField,
	MessageRequest,
	MessageResponse,
	OtpStartResponse,
	OtpVerifyFailure,
	TransactionOption,
	UiPrompt,
} from "@/lib/contract";
import { type Copy, copy, LANGUAGES, type Language } from "@/lib/i18n";

/**
 * Web chat (F02): simulated OTP login, ES/PT, and transaction cards to pick
 * from. All calls go to this app's /api routes, which forward to the backend
 * and keep the session token in an httpOnly cookie.
 *
 * When the session lapses mid-conversation (R27) the chat returns to login,
 * keeps the transcript and conversationId, and resends the pending turn once
 * the customer verifies again.
 */

type Turn = Omit<MessageRequest, "conversationId" | "language">;

interface Message {
	id: number;
	role: "agent" | "user";
	text: string;
	prompt?: UiPrompt | null;
	handoff?: { caseId: string; queue: string } | null;
}

type Phase =
	| { step: "ref" }
	| { step: "code"; challenge: OtpStartResponse }
	| { step: "chat" };

let nextId = 1;

async function postJson<T>(
	url: string,
	body: unknown,
): Promise<{ status: number; data: T | null }> {
	try {
		const res = await fetch(url, {
			method: "POST",
			headers: { "content-type": "application/json" },
			body: JSON.stringify(body),
		});
		const data = (await res.json().catch(() => null)) as T | null;
		return { status: res.status, data };
	} catch {
		return { status: 0, data: null };
	}
}

export function Chat() {
	const [lang, setLang] = useState<Language>("es");
	const t = copy[lang];

	const [phase, setPhase] = useState<Phase>({ step: "ref" });
	const [notice, setNotice] = useState<string | null>(null);
	const [messages, setMessages] = useState<Message[]>([]);
	const [conversationId, setConversationId] = useState<string | undefined>();
	const [pending, setPending] = useState<Turn | null>(null);
	const [busy, setBusy] = useState(false);
	const [ended, setEnded] = useState(false);
	const [draft, setDraft] = useState("");
	const listRef = useRef<HTMLOListElement>(null);

	// biome-ignore lint/correctness/useExhaustiveDependencies: scroll on new messages
	useEffect(() => {
		listRef.current?.lastElementChild?.scrollIntoView({ block: "end" });
	}, [messages]);

	const push = (m: Omit<Message, "id">) =>
		setMessages((prev) => [...prev, { ...m, id: nextId++ }]);

	async function send(turn: Turn, echo: string | null) {
		if (echo) push({ role: "user", text: echo });
		setBusy(true);
		const { status, data } = await postJson<MessageResponse>("/api/chat", {
			...turn,
			conversationId,
			language: lang,
		});
		setBusy(false);

		if (status === 401) {
			// R27: re-authenticate, then resend this same turn.
			setPending(turn);
			setNotice(t.reauth);
			setPhase({ step: "ref" });
			return;
		}
		if (status !== 200 || !data) {
			push({ role: "agent", text: t.error });
			return;
		}
		setConversationId(data.conversationId);
		setEnded(data.state.ended);
		push({
			role: "agent",
			text: data.reply.text,
			prompt: data.prompt,
			handoff: data.state.handoff,
		});
	}

	async function onLoggedIn() {
		setPhase({ step: "chat" });
		setNotice(null);
		if (pending) {
			const turn = pending;
			setPending(null);
			await send(turn, null);
		} else if (messages.length === 0) {
			push({ role: "agent", text: t.welcome });
		}
	}

	function onSubmitText(e: FormEvent) {
		e.preventDefault();
		const text = draft.trim();
		if (!text || busy) return;
		setDraft("");
		void send({ text }, text);
	}

	function onPick(option: TransactionOption) {
		void send(
			{ selection: { transactionId: option.transactionId } },
			`${t.youSelected} ${option.merchant}, ${formatAmount(option, lang)}`,
		);
	}

	function onConfirm(field: ConfirmField, value: boolean) {
		void send({ confirmation: { field, value } }, value ? t.yes : t.no);
	}

	function restart() {
		setMessages([{ id: nextId++, role: "agent", text: t.welcome }]);
		setConversationId(undefined);
		setEnded(false);
	}

	const lastAgent = [...messages].reverse().find((m) => m.role === "agent");

	return (
		<section className="chat" aria-label={t.title} lang={lang}>
			<header className="chat-header">
				<div>
					<h1>{t.title}</h1>
					<p className="muted">{t.subtitle}</p>
				</div>
				<label className="lang">
					<span className="sr-only">{t.language}</span>
					<select
						value={lang}
						onChange={(e) => setLang(e.target.value as Language)}
					>
						{LANGUAGES.map((l) => (
							<option key={l} value={l}>
								{l.toUpperCase()}
							</option>
						))}
					</select>
				</label>
			</header>

			{phase.step !== "chat" ? (
				<Login
					t={t}
					lang={lang}
					phase={phase}
					notice={notice}
					onChallenge={(challenge) => setPhase({ step: "code", challenge })}
					onReset={() => setPhase({ step: "ref" })}
					onVerified={onLoggedIn}
				/>
			) : (
				<>
					<ol className="messages" aria-live="polite" ref={listRef}>
						{messages.map((m) => (
							<li key={m.id} className={`bubble ${m.role}`}>
								<p>{m.text}</p>
								{m.handoff && (
									<p className="handoff">
										{t.handoff} <strong>{m.handoff.caseId}</strong>
									</p>
								)}
								{m.prompt && m === lastAgent && !busy && (
									<PromptView
										t={t}
										lang={lang}
										prompt={m.prompt}
										onPick={onPick}
										onConfirm={onConfirm}
									/>
								)}
							</li>
						))}
						{busy && (
							<li className="bubble agent typing" aria-label="...">
								<span />
								<span />
								<span />
							</li>
						)}
					</ol>

					{ended ? (
						<div className="composer">
							<p className="muted">{t.ended}</p>
							<button type="button" onClick={restart}>
								{t.newChat}
							</button>
						</div>
					) : (
						<form className="composer" onSubmit={onSubmitText}>
							<input
								type="text"
								value={draft}
								onChange={(e) => setDraft(e.target.value)}
								placeholder={t.placeholder}
								aria-label={t.placeholder}
								maxLength={2000}
								disabled={busy}
							/>
							<button type="submit" disabled={busy || !draft.trim()}>
								{t.send}
							</button>
						</form>
					)}
				</>
			)}
		</section>
	);
}

function Login({
	t,
	lang,
	phase,
	notice,
	onChallenge,
	onReset,
	onVerified,
}: {
	t: Copy;
	lang: Language;
	phase: Exclude<Phase, { step: "chat" }>;
	notice: string | null;
	onChallenge: (c: OtpStartResponse) => void;
	onReset: () => void;
	onVerified: () => void;
}) {
	const [value, setValue] = useState("");
	const [error, setError] = useState<string | null>(null);
	const [busy, setBusy] = useState(false);
	const [blocked, setBlocked] = useState(false);

	async function submit(e: FormEvent) {
		e.preventDefault();
		if (!value.trim() || busy) return;
		setBusy(true);
		setError(null);
		if (phase.step === "ref") {
			const { status, data } = await postJson<OtpStartResponse>(
				"/api/session/otp",
				{ customerRef: value.trim(), language: lang },
			);
			setBusy(false);
			if (status === 200 && data) {
				setValue("");
				onChallenge(data);
			} else {
				setError(t.error);
			}
			return;
		}
		const { status, data } = await postJson<OtpVerifyFailure>(
			"/api/session/verify",
			{ challengeId: phase.challenge.challengeId, code: value.trim() },
		);
		setBusy(false);
		if (status === 200) {
			onVerified();
			return;
		}
		setValue("");
		if (data?.status === "blocked") setBlocked(true);
		setError(data?.message ?? t.error);
	}

	return (
		<form className="login" onSubmit={submit}>
			{notice && (
				<p role="status" className="notice">
					{notice}
				</p>
			)}
			<h2>{t.loginTitle}</h2>
			{phase.step === "ref" ? (
				<p className="muted">{t.loginHelp}</p>
			) : (
				<>
					<p className="muted">
						{t.codeSentTo} {phase.challenge.destinationHint}
					</p>
					{phase.challenge.demoCode && (
						<p className="demo-code">
							{t.demoCode} <code>{phase.challenge.demoCode}</code>
						</p>
					)}
				</>
			)}
			<label className="field">
				<span>{phase.step === "ref" ? t.customerRef : t.codeLabel}</span>
				<input
					value={value}
					onChange={(e) => setValue(e.target.value)}
					inputMode={phase.step === "code" ? "numeric" : "text"}
					autoComplete={phase.step === "code" ? "one-time-code" : "off"}
					maxLength={phase.step === "code" ? 8 : 64}
					disabled={busy || blocked}
				/>
			</label>
			{error && (
				<p role="alert" className="notice">
					{error}
				</p>
			)}
			<div className="row">
				<button type="submit" disabled={busy || blocked || !value.trim()}>
					{phase.step === "ref" ? t.sendCode : t.verify}
				</button>
				{phase.step === "code" && !blocked && (
					<button type="button" className="link" onClick={onReset}>
						{t.changeRef}
					</button>
				)}
			</div>
		</form>
	);
}

function PromptView({
	t,
	lang,
	prompt,
	onPick,
	onConfirm,
}: {
	t: Copy;
	lang: Language;
	prompt: UiPrompt;
	onPick: (o: TransactionOption) => void;
	onConfirm: (field: ConfirmField, value: boolean) => void;
}) {
	if (prompt.type === "transaction_choices") {
		return (
			<div className="choices" role="group" aria-label={t.pickOne}>
				{prompt.options.map((o) => (
					<button
						key={o.transactionId}
						type="button"
						className="card"
						onClick={() => onPick(o)}
					>
						<TxnCard t={t} lang={lang} txn={o} />
					</button>
				))}
			</div>
		);
	}
	const question =
		prompt.field === "recognizesCharge" ? t.recognizeQuestion : t.blockQuestion;
	return (
		<div className="choices" role="group" aria-label={question}>
			{prompt.transaction && (
				<div className="card static">
					<TxnCard t={t} lang={lang} txn={prompt.transaction} />
				</div>
			)}
			<div className="row">
				<button type="button" onClick={() => onConfirm(prompt.field, true)}>
					{t.yes}
				</button>
				<button
					type="button"
					className="secondary"
					onClick={() => onConfirm(prompt.field, false)}
				>
					{t.no}
				</button>
			</div>
		</div>
	);
}

function TxnCard({
	t,
	lang,
	txn,
}: {
	t: Copy;
	lang: Language;
	txn: TransactionOption;
}) {
	return (
		<>
			<span className="card-merchant">{txn.merchant}</span>
			<span className="card-amount">{formatAmount(txn, lang)}</span>
			<span className="card-meta">
				{formatDate(txn.date, lang)} · {t.status[txn.status]}
			</span>
		</>
	);
}

/** Original currency, as on the customer's statement. */
function formatAmount(txn: TransactionOption, lang: Language): string {
	try {
		return new Intl.NumberFormat(lang === "pt" ? "pt-BR" : "es", {
			style: "currency",
			currency: txn.currency,
		}).format(txn.amount);
	} catch {
		return `${txn.amount} ${txn.currency}`;
	}
}

function formatDate(iso: string, lang: Language): string {
	// Date-only values are calendar dates; format in UTC so no shift by a day.
	return new Intl.DateTimeFormat(lang === "pt" ? "pt-BR" : "es", {
		day: "numeric",
		month: "short",
		year: "numeric",
		timeZone: "UTC",
	}).format(new Date(`${iso}T00:00:00Z`));
}

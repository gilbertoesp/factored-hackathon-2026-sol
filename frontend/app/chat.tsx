"use client";

import { useState } from "react";
import { copy, LANGUAGES, type Language } from "@/lib/i18n";

/**
 * Chat shell. The composer is disabled until the conversation API (B01) is
 * wired in F02; the layout, language switch and message list are final.
 */
export function Chat() {
	const [lang, setLang] = useState<Language>("es");
	const t = copy[lang];

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

			<ol className="messages" aria-live="polite">
				<li className="bubble agent">{t.welcome}</li>
			</ol>

			<form className="composer" onSubmit={(e) => e.preventDefault()}>
				<input
					type="text"
					placeholder={t.placeholder}
					aria-label={t.placeholder}
					disabled
				/>
				<button type="submit" disabled>
					{t.send}
				</button>
			</form>
			<p className="muted small">{t.offline}</p>
		</section>
	);
}

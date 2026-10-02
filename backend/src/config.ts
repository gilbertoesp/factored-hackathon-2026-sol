import { z } from "zod";

/**
 * Boot-time environment contract. A missing or blank secret is a
 * misconfiguration, and the only alternative to failing here is failing
 * later as a 401 on every webhook, which reads as a Meta outage rather than a
 * missing variable.
 */
const envSchema = z
	.object({
		PORT: z.coerce.number().int().min(1).max(65_535).default(4000),
		WHATSAPP_APP_SECRET: z.string().min(1),
		WHATSAPP_VERIFY_TOKEN: z.string().min(1),
		// Optional: without it the advisor view is off. Blank counts as unset, since
		// compose passes ${ADVISOR_API_TOKEN:-} as an empty string.
		ADVISOR_API_TOKEN: z.preprocess(
			(v) => (v === "" ? undefined : v),
			z.string().min(16).optional(),
		),
		// Optional pair: without both, fichas live in memory (lost on restart).
		// One without the other is a typo, not a choice, so it fails boot.
		SUPABASE_URL: z.preprocess(
			(v) => (v === "" ? undefined : v),
			z.string().url().optional(),
		),
		SUPABASE_SERVICE_ROLE_KEY: z.preprocess(
			(v) => (v === "" ? undefined : v),
			z.string().min(1).optional(),
		),
	})
	.superRefine((env, ctx) => {
		if (Boolean(env.SUPABASE_URL) !== Boolean(env.SUPABASE_SERVICE_ROLE_KEY)) {
			const missing = env.SUPABASE_URL
				? "SUPABASE_SERVICE_ROLE_KEY"
				: "SUPABASE_URL";
			ctx.addIssue({
				code: z.ZodIssueCode.custom,
				path: [missing],
				message: "set both Supabase variables or neither",
			});
		}
	});

export interface Config {
	port: number;
	whatsapp: {
		appSecret: string;
		verifyToken: string;
	};
	advisorToken: string | undefined;
	supabase: { url: string; serviceRoleKey: string } | undefined;
}

export class ConfigError extends Error {
	readonly missing: string[];

	constructor(missing: string[]) {
		// Names only. The rejected values are secrets and never reach the log.
		super(`invalid environment: missing or blank ${missing.join(", ")}`);
		this.name = "ConfigError";
		this.missing = missing;
	}
}

/**
 * Validates the environment. Every problem is reported at once, because fixing
 * one variable per boot cycle burns a deploy on each typo.
 */
export function loadConfig(env: Record<string, string | undefined>): Config {
	const result = envSchema.safeParse(env);
	if (!result.success) {
		throw new ConfigError([
			...new Set(result.error.issues.map((i) => i.path.join("."))),
		]);
	}

	return {
		port: result.data.PORT,
		whatsapp: {
			appSecret: result.data.WHATSAPP_APP_SECRET,
			verifyToken: result.data.WHATSAPP_VERIFY_TOKEN,
		},
		advisorToken: result.data.ADVISOR_API_TOKEN,
		supabase:
			result.data.SUPABASE_URL && result.data.SUPABASE_SERVICE_ROLE_KEY
				? {
						url: result.data.SUPABASE_URL,
						serviceRoleKey: result.data.SUPABASE_SERVICE_ROLE_KEY,
					}
				: undefined,
	};
}

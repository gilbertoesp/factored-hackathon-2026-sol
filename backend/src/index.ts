import type { HealthState } from "./app";
import { createApp } from "./app";
import { ConfigError, loadConfig } from "./config";

// Validated before the server binds. A missing secret must fail the deploy, not
// the first webhook, where it reads as a Meta outage.
function build(): { state: HealthState; port: number } {
	try {
		const config = loadConfig(process.env);
		return { state: { valid: true, errors: [] }, port: config.port };
	} catch (error) {
		if (!(error instanceof ConfigError)) throw error;
		// Bind anyway, reporting 503 on /health. An orchestrator decides
		// readiness from that, and a process that exits instead cannot say which
		// variable was wrong.
		console.error(`backend misconfigured: ${error.message}`);
		return {
			state: { valid: false, errors: error.missing },
			port: Number(process.env.PORT ?? 4000),
		};
	}
}

const { state, port } = build();

export const app = createApp({ config: state });
export const server = Bun.serve({ port, fetch: app.fetch });

console.log(`backend listening on :${port}`);

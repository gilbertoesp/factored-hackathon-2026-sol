import type { Hono } from "hono";
import { createApp } from "./app";
import { ConfigError, loadConfig } from "./config";
import { createOtelTelemetry } from "./telemetry";

interface Booted {
	port: number;
	build: () => Hono;
	shutdown: () => Promise<void>;
}

// Validated before the server binds. A missing secret must fail the deploy, not
// the first webhook, where it reads as a Meta outage.
function boot(): Booted {
	try {
		const config = loadConfig(process.env);
		const traces = createOtelTelemetry({
			serviceName: "whatsapp-backend",
			otlpEndpoint:
				process.env.OTEL_EXPORTER_OTLP_ENDPOINT ?? "http://localhost:4318",
		});

		return {
			port: config.port,
			build: () =>
				createApp({
					secrets: {
						appSecret: config.whatsapp.appSecret,
						verifyToken: config.whatsapp.verifyToken,
					},
					telemetry: traces.telemetry,
				}),
			shutdown: () => traces.shutdown(),
		};
	} catch (error) {
		if (!(error instanceof ConfigError)) throw error;

		// Bind anyway, reporting 503 on /health. An orchestrator decides
		// readiness from that, and a process that exits instead cannot say which
		// variable was wrong. No secrets are passed down, so no route can serve
		// with a blank one.
		console.error(`backend misconfigured: ${error.message}`);
		return {
			port: Number(process.env.PORT ?? 4000),
			build: () =>
				createApp({ config: { valid: false, errors: error.missing } }),
			shutdown: async () => {},
		};
	}
}

const { port, build, shutdown } = boot();

export const app = build();
export const server = Bun.serve({ port, fetch: app.fetch });

console.log(`backend listening on :${port}`);

for (const signal of ["SIGINT", "SIGTERM"] as const) {
	process.on(signal, () => {
		// A batch that has not been flushed yet is lost without this, which is
		// exactly the last batch before a deploy that is worth having.
		void shutdown().then(() => {
			server.stop();
			process.exit(0);
		});
	});
}

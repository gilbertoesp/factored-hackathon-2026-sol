import { createApp } from "./app";
import { loadConfig } from "./config";
import { createOtelTelemetry } from "./telemetry";

// Validated before the server binds, so a missing secret fails the deploy
// rather than the first webhook. app.ts's own defaults are only reachable
// through tests, which inject their own secrets.
const config = loadConfig(process.env);

const traces = createOtelTelemetry({
	serviceName: "whatsapp-backend",
	otlpEndpoint:
		process.env.OTEL_EXPORTER_OTLP_ENDPOINT ?? "http://localhost:4318",
});

export const app = createApp({
	secrets: {
		appSecret: config.whatsapp.appSecret,
		verifyToken: config.whatsapp.verifyToken,
	},
	telemetry: traces.telemetry,
});

export const server = Bun.serve({ port: config.port, fetch: app.fetch });

console.log(`backend listening on :${config.port}`);

for (const signal of ["SIGINT", "SIGTERM"] as const) {
	process.on(signal, () => {
		// A batch that has not been flushed yet is lost without this, which is
		// exactly the last batch before a deploy that is worth having.
		void traces.shutdown().then(() => {
			server.stop();
			process.exit(0);
		});
	});
}

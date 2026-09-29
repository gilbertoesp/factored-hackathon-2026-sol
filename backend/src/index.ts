import { createApp } from "./app";
import { loadConfig } from "./config";

// Validated before the server binds, so a missing secret fails the deploy
// rather than the first webhook. app.ts's own defaults are only reachable
// through tests, which inject their own secrets.
const config = loadConfig(process.env);

export const app = createApp({
	secrets: {
		appSecret: config.whatsapp.appSecret,
		verifyToken: config.whatsapp.verifyToken,
	},
});

export const server = Bun.serve({ port: config.port, fetch: app.fetch });

console.log(`backend listening on :${config.port}`);

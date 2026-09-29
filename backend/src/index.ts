import { app } from "./app";

const port = Number(process.env.PORT ?? 4000);

export const server = Bun.serve({ port, fetch: app.fetch });

console.log(`backend listening on :${port}`);

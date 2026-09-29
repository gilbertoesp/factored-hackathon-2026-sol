import { expect, test } from "bun:test";
import { app } from "../../app";

const url = "http://localhost";

test("Entry Seam: POST /api/whatsapp/webhook returns 200", async () => {
	const res = await app.fetch(
		new Request(`${url}/api/whatsapp/webhook`, { method: "POST" }),
	);

	expect(res.status).toBe(200);
	expect(await res.json()).toEqual({ status: "ok" });
});

import { expect, test } from "bun:test";
import { app } from "../../app";

const url = "http://localhost";

test("Exit Seam: POST /api/whatsapp/handler returns 200", async () => {
	const res = await app.fetch(
		new Request(`${url}/api/whatsapp/handler`, { method: "POST" }),
	);

	expect(res.status).toBe(200);
	expect(await res.json()).toEqual({ status: "accepted" });
});

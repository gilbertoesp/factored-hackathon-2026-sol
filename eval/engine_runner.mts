// Puente Python -> motor de reglas real (backend/src/rules/engine.ts de feat/rules-engine).
// Lee por stdin un arreglo JSON de `Facts` y escribe por stdout un arreglo de decisiones, en el mismo orden.
// Uso: ENGINE_DIR=<carpeta con engine.ts, policy.ts y rules.json> tsx eval/engine_runner.mts < facts.json
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { join } from "node:path";

const dir = process.env.ENGINE_DIR;
if (!dir) throw new Error("Define ENGINE_DIR (carpeta rules/ del motor)");
const { decide } = await import(pathToFileURL(join(dir, "engine.ts")).href);
const facts: unknown[] = JSON.parse(readFileSync(0, "utf8"));
console.log(JSON.stringify(facts.map((f) => {
	try {
		return decide(f);
	} catch (e) {
		return { kind: "error", error: String(e) };
	}
})));

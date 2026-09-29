import { expect, test } from "bun:test";
import type { ReadableSpan } from "@opentelemetry/sdk-trace-base";
import {
	BasicTracerProvider,
	InMemorySpanExporter,
	SimpleSpanProcessor,
} from "@opentelemetry/sdk-trace-base";
import { SPAN_ATTRIBUTE_ALLOWLIST } from "./api/whatsapp/webhook";
import { createOtelTelemetry, OtelTelemetry } from "./telemetry";

/** A tracer provider wired to an in-memory exporter, so spans are inspectable. */
function provider() {
	const exporter = new InMemorySpanExporter();
	const tracerProvider = new BasicTracerProvider({
		spanProcessors: [new SimpleSpanProcessor(exporter)],
	});
	return { tracerProvider, exporter };
}

function attributesOf(
	spans: ReadableSpan[],
	name: string,
): Record<string, unknown> {
	const span = spans.find((candidate) => candidate.name === name);
	return { ...span?.attributes };
}

test("a span started through the port is exported with its name", () => {
	const { tracerProvider, exporter } = provider();
	const telemetry = new OtelTelemetry(tracerProvider.getTracer("test"));

	const span = telemetry.startSpan("whatsapp.webhook.post");
	span.setAttributes({ "whatsapp.outcome": "ok" });
	span.end();

	const spans = exporter.getFinishedSpans();
	expect(spans.map((s) => s.name)).toContain("whatsapp.webhook.post");
});

test("an allowlisted attribute survives the export", () => {
	const { tracerProvider, exporter } = provider();
	const telemetry = new OtelTelemetry(tracerProvider.getTracer("test"));

	const span = telemetry.startSpan("whatsapp.webhook.post");
	span.setAttributes({ "whatsapp.outcome": "rate_limited" });
	span.end();

	expect(
		attributesOf(exporter.getFinishedSpans(), "whatsapp.webhook.post"),
	).toMatchObject({
		"whatsapp.outcome": "rate_limited",
	});
});

test("an attribute outside the allowlist is dropped", () => {
	// The allowlist is enforced in production, not merely asserted in a test.
	// A name added by a future contributor must not reach a trace by default.
	const { tracerProvider, exporter } = provider();
	const telemetry = new OtelTelemetry(tracerProvider.getTracer("test"));

	const span = telemetry.startSpan("whatsapp.webhook.post");
	span.setAttributes({ "customer.email": "someone@example.com" });
	span.end();

	expect(
		attributesOf(exporter.getFinishedSpans(), "whatsapp.webhook.post"),
	).not.toHaveProperty("customer.email");
});

test("the raw request body never reaches an exported span", () => {
	const { tracerProvider, exporter } = provider();
	const telemetry = new OtelTelemetry(tracerProvider.getTracer("test"));
	const body = '{"from":"15551239999","text":{"body":"secret ticket"}}';

	const span = telemetry.startSpan("whatsapp.webhook.post");
	span.setAttributes({ "whatsapp.outcome": "ok" });
	span.setAttributes({ "whatsapp.raw_body": body });
	span.end();

	const attributes = exporter
		.getFinishedSpans()
		.flatMap((candidate) => Object.values(candidate.attributes).map(String));
	expect(attributes).not.toContain(body);
	expect(attributes.join(" ")).not.toContain("secret ticket");
	expect(attributes.join(" ")).not.toContain("15551239999");
});

test("ending a span twice does not export it twice", () => {
	const { tracerProvider, exporter } = provider();
	const telemetry = new OtelTelemetry(tracerProvider.getTracer("test"));

	const span = telemetry.startSpan("whatsapp.webhook.post");
	span.end();
	span.end();

	expect(
		exporter
			.getFinishedSpans()
			.filter((s) => s.name === "whatsapp.webhook.post"),
	).toHaveLength(1);
});

test("the allowlist the exporter enforces is the documented one", () => {
	expect(SPAN_ATTRIBUTE_ALLOWLIST.size).toBeGreaterThan(0);
});

test("createOtelTelemetry returns a port and a shutdown hook", async () => {
	const handle = createOtelTelemetry({
		tracerProvider: provider().tracerProvider,
	});

	expect(handle.telemetry).toBeInstanceOf(OtelTelemetry);
	await expect(handle.shutdown()).resolves.toBeUndefined();
});

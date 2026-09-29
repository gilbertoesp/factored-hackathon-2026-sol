import type { Span, Tracer } from "@opentelemetry/api";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { Resource } from "@opentelemetry/resources";
import {
	BasicTracerProvider,
	BatchSpanProcessor,
	type SpanExporter,
} from "@opentelemetry/sdk-trace-base";
import type {
	SpanAttributes,
	SpanHandle,
	TelemetryPort,
} from "./api/whatsapp/webhook";
import { SPAN_ATTRIBUTE_ALLOWLIST } from "./api/whatsapp/webhook";

/**
 * TelemetryPort backed by a real OpenTelemetry tracer.
 *
 * The attribute allowlist is enforced here rather than left to reviewer
 * discipline: a name outside it is dropped, so a future contributor who adds an
 * attribute carrying customer data cannot leak it by forgetting a test.
 */
export class OtelTelemetry implements TelemetryPort {
	private readonly tracer: Tracer;

	constructor(tracer: Tracer) {
		this.tracer = tracer;
	}

	startSpan(name: string, attributes: SpanAttributes = {}): SpanHandle {
		const span = this.tracer.startSpan(name);
		this.apply(span, attributes);

		let ended = false;
		return {
			setAttributes: (next: SpanAttributes) => this.apply(span, next),
			end: () => {
				// A retried branch could end twice; the exporter would then
				// count one request as two.
				if (ended) return;
				ended = true;
				span.end();
			},
		};
	}

	private apply(span: Span, attributes: SpanAttributes): void {
		for (const [key, value] of Object.entries(attributes)) {
			if (!SPAN_ATTRIBUTE_ALLOWLIST.has(key)) continue;
			span.setAttribute(key, value);
		}
	}
}

export interface TelemetryHandle {
	telemetry: TelemetryPort;
	shutdown(): Promise<void>;
}

export interface OtelOptions {
	/** Injected in tests; production builds a provider from the endpoint. */
	tracerProvider?: BasicTracerProvider;
	serviceName?: string;
	otlpEndpoint?: string;
	exporter?: SpanExporter;
}

/**
 * Builds the tracer and returns a shutdown hook. The process must await the
 * hook on SIGTERM, or a batch that has not been flushed yet is lost.
 */
export function createOtelTelemetry(
	options: OtelOptions = {},
): TelemetryHandle {
	const tracerProvider =
		options.tracerProvider ??
		new BasicTracerProvider({
			resource: new Resource({
				"service.name": options.serviceName ?? "whatsapp-backend",
			}),
			spanProcessors: [
				new BatchSpanProcessor(
					options.exporter ??
						new OTLPTraceExporter({
							url: `${options.otlpEndpoint ?? "http://localhost:4318"}/v1/traces`,
						}),
				),
			],
		});

	return {
		telemetry: new OtelTelemetry(tracerProvider.getTracer("whatsapp")),
		shutdown: () => tracerProvider.shutdown(),
	};
}

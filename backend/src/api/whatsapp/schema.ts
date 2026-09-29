import { z } from "zod";

/**
 * Schema for the WhatsApp Cloud API notification envelope. The outer object is
 * strict so an unrecognized top-level key is rejected rather than silently
 * accepted, and `changes[].field` discriminates the two payload shapes Meta
 * subscribable fields produce.
 */

const contactSchema = z.object({
	wa_id: z.string(),
});

const metadataSchema = z.object({
	display_phone_number: z.string(),
	phone_number_id: z.string(),
});

const textSchema = z.object({ body: z.string() });

const messageSchema = z
	.object({
		from: z.string(),
		id: z.string().min(1),
		timestamp: z.union([z.string(), z.number()]),
		type: z.string(),
		text: textSchema.optional(),
		context: z
			.object({
				from: z.string(),
				id: z.string(),
			})
			.optional(),
		contacts: z.array(contactSchema).optional(),
	})
	.passthrough();

const statusSchema = z
	.object({
		id: z.string().min(1),
		recipient_id: z.string(),
		status: z.enum(["read", "delivered", "sent", "failed", "deleted"]),
		timestamp: z.union([z.string(), z.number()]),
		errors: z.array(z.unknown()).optional(),
	})
	.passthrough();

const messagesValueSchema = z
	.object({
		messaging_product: z.literal("whatsapp"),
		metadata: metadataSchema,
		messages: z.array(messageSchema).min(1),
		statuses: z.undefined().optional(),
	})
	.passthrough();

const statusesValueSchema = z
	.object({
		messaging_product: z.literal("whatsapp"),
		metadata: metadataSchema,
		statuses: z.array(statusSchema).min(1),
		messages: z.undefined().optional(),
	})
	.passthrough();

const changeSchema = z.discriminatedUnion("field", [
	z.object({ field: z.literal("messages"), value: messagesValueSchema }),
	z.object({ field: z.literal("statuses"), value: statusesValueSchema }),
]);

const entrySchema = z.object({
	id: z.string().min(1),
	changes: z.array(changeSchema).min(1),
});

export const notificationSchema = z
	.object({
		object: z.literal("whatsapp_business_account"),
		entry: z.array(entrySchema).min(1),
	})
	.strict();

export type WhatsAppNotification = z.infer<typeof notificationSchema>;

/** Parses the raw body, returning issue paths only — never the body itself. */
export function parseNotification(
	rawBody: string,
): { ok: true; value: WhatsAppNotification } | { ok: false; issues: string[] } {
	let json: unknown;
	try {
		json = JSON.parse(rawBody);
	} catch {
		return { ok: false, issues: ["body: not valid JSON"] };
	}

	const result = notificationSchema.safeParse(json);
	if (!result.success) {
		return {
			ok: false,
			issues: result.error.issues.map(
				(issue) => issue.path.join(".") || "body",
			),
		};
	}
	return { ok: true, value: result.data };
}

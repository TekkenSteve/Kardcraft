export type RuntimeEnvelope = {
    schema_version: "agentos.conversation.v1";
    event_id: string;
    occurred_at: string;
    thread_id: string;
    run_id: string;
    process_id?: string;
    event_type: string;
    sequence: number;
    payload: Record<string, unknown>;
};

export type RuntimeEnvelopeValidationResult =
    | { ok: true; value: RuntimeEnvelope }
    | { ok: false; reason: string };

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === "object" && value !== null && !Array.isArray(value);

const isNonEmptyString = (value: unknown): value is string =>
    typeof value === "string" && value.trim().length > 0;

export function validateRuntimeEnvelope(raw: unknown): RuntimeEnvelopeValidationResult {
    if (!isRecord(raw)) return { ok: false, reason: "invalid_object" };

    if (raw.schema_version !== "agentos.conversation.v1") return { ok: false, reason: "invalid_schema_version" };
    if (!isNonEmptyString(raw.event_id)) return { ok: false, reason: "missing_event_id" };
    if (!isNonEmptyString(raw.occurred_at) || Number.isNaN(Date.parse(raw.occurred_at))) {
        return { ok: false, reason: "invalid_occurred_at" };
    }
    if (!isNonEmptyString(raw.thread_id)) return { ok: false, reason: "missing_thread_id" };
    if (!isNonEmptyString(raw.run_id)) return { ok: false, reason: "missing_run_id" };
    if (!isNonEmptyString(raw.event_type)) return { ok: false, reason: "missing_event_type" };
    if (typeof raw.sequence !== "number" || !Number.isSafeInteger(raw.sequence) || raw.sequence <= 0) {
        return { ok: false, reason: "invalid_sequence" };
    }
    if (!isRecord(raw.payload)) return { ok: false, reason: "invalid_payload" };

    return {
        ok: true,
        value: {
            schema_version: raw.schema_version,
            event_id: raw.event_id,
            occurred_at: raw.occurred_at,
            thread_id: raw.thread_id,
            run_id: raw.run_id,
            process_id: isNonEmptyString(raw.process_id) ? raw.process_id : undefined,
            event_type: raw.event_type,
            sequence: raw.sequence,
            payload: raw.payload,
        },
    };
}

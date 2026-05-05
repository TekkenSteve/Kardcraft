export type RuntimeEnvelope = {
    schema_version: number;
    correlation_id: string;
    event_id: string;
    occurred_at: string;
    workflow_id: string;
    run_id: string;
    session_id: string;
    event_type: string;
    stream_id?: string;
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

    if (raw.schema_version !== 1) return { ok: false, reason: "invalid_schema_version" };
    if (!isNonEmptyString(raw.correlation_id)) return { ok: false, reason: "missing_correlation_id" };
    if (!isNonEmptyString(raw.event_id)) return { ok: false, reason: "missing_event_id" };
    if (!isNonEmptyString(raw.occurred_at) || Number.isNaN(Date.parse(raw.occurred_at))) {
        return { ok: false, reason: "invalid_occurred_at" };
    }
    if (!isNonEmptyString(raw.workflow_id)) return { ok: false, reason: "missing_workflow_id" };
    if (!isNonEmptyString(raw.run_id)) return { ok: false, reason: "missing_run_id" };
    if (!isNonEmptyString(raw.session_id)) return { ok: false, reason: "missing_session_id" };
    if (!isNonEmptyString(raw.event_type)) return { ok: false, reason: "missing_event_type" };
    if (!isRecord(raw.payload)) return { ok: false, reason: "invalid_payload" };

    return {
        ok: true,
        value: {
            schema_version: raw.schema_version,
            correlation_id: raw.correlation_id,
            event_id: raw.event_id,
            occurred_at: raw.occurred_at,
            workflow_id: raw.workflow_id,
            run_id: raw.run_id,
            session_id: raw.session_id,
            event_type: raw.event_type,
            stream_id: isNonEmptyString(raw.stream_id) ? raw.stream_id : undefined,
            payload: raw.payload,
        },
    };
}

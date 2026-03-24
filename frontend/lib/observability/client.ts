export type TelemetryPayload = Record<string, unknown>;

export function logEvent(name: string, payload: TelemetryPayload = {}) {
    if (process.env.NODE_ENV !== "production") {
        console.info(`[Telemetry] ${name}`, payload);
    }
}

export function logError(error: unknown, payload: TelemetryPayload = {}) {
    if (process.env.NODE_ENV !== "production") {
        console.error("[Telemetry] error", error, payload);
    }
}

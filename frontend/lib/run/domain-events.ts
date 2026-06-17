import { EventType, RunEvent } from "@/lib/kardcraft/types";
import type { ControlErrorCode, DomainEventMapResult, RunDomainEvent } from "./domain-event-types";
export type { ControlErrorCode, DomainEventMapResult, DomainEventRejectReason, RunDomainEvent } from "./domain-event-types";

type WireEventInput = {
    eventType: string;
    payload: Record<string, unknown>;
    fallbackWorkflowId: string;
    fallbackSessionId?: string | null;
    at: string;
    eventId: string;
};

function asString(value: unknown): string | null {
    if (typeof value !== "string") return null;
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
}

function asNumber(value: unknown): number | undefined {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string") {
        const parsed = Number(value);
        if (Number.isFinite(parsed)) return parsed;
    }
    return undefined;
}

function normalizeControlErrorCode(raw: string | null): ControlErrorCode {
    const normalized = (raw || "").trim().toLowerCase();
    const codeMap: Record<string, ControlErrorCode> = {
        "invalid-transition": "INVALID_TRANSITION",
        "task-not-found": "TASK_NOT_FOUND",
        "session-mismatch": "SESSION_MISMATCH",
        "authz-denied": "AUTHZ_DENIED",
        "conflict": "CONFLICT",
        "timeout": "TIMEOUT",
        "transport-unavailable": "TRANSPORT_UNAVAILABLE",
        "internal": "INTERNAL",
    };
    return codeMap[normalized] || "INTERNAL";
}

function resolveWorkflowId(payload: Record<string, unknown>, fallbackWorkflowId: string): string | null {
    return (
        asString(payload.workflow_id) ||
        asString(payload.task_id) ||
        fallbackWorkflowId ||
        null
    );
}

function resolveSessionId(payload: Record<string, unknown>, fallbackSessionId?: string | null): string | null {
    const fromTopLevel = asString(payload.session_id);
    if (fromTopLevel) return fromTopLevel;
    const nestedPayload = payload.payload;
    if (nestedPayload && typeof nestedPayload === "object") {
        const nestedSessionId = asString((nestedPayload as Record<string, unknown>).session_id);
        if (nestedSessionId) return nestedSessionId;
    }
    return fallbackSessionId || null;
}

function resolveRunId(payload: Record<string, unknown>): string | null {
    const fromTopLevel = asString(payload.run_id);
    if (fromTopLevel) return fromTopLevel;
    const nestedPayload = payload.payload;
    if (nestedPayload && typeof nestedPayload === "object") {
        const nestedRunId = asString((nestedPayload as Record<string, unknown>).run_id);
        if (nestedRunId) return nestedRunId;
    }
    return null;
}

function normalizeCompletedContent(payload: Record<string, unknown>): string {
    const response = asString(payload.response);
    if (response) return response;
    const content = payload.content;
    if (typeof content === "string" && content.trim().length > 0) return content;
    if (content && typeof content === "object") {
        const objectContent = content as Record<string, unknown>;
        const textCandidate =
            asString(objectContent.text) ||
            asString(objectContent.content) ||
            asString(objectContent.message);
        if (textCandidate) return textCandidate;
        try {
            return JSON.stringify(content);
        } catch {
            return "";
        }
    }
    const nestedPayload = payload.payload;
    if (nestedPayload && typeof nestedPayload === "object") {
        const nested = nestedPayload as Record<string, unknown>;
        const nestedResponse = asString(nested.response);
        if (nestedResponse) return nestedResponse;
        const nestedMessage = asString(nested.message);
        if (nestedMessage) return nestedMessage;
        const nestedText = asString(nested.text);
        if (nestedText) return nestedText;
        const nestedContent = nested.content;
        if (typeof nestedContent === "string" && nestedContent.trim().length > 0) return nestedContent;
    }
    return "";
}

function terminalResultPayload(payload: Record<string, unknown>): unknown {
    if (payload.result !== undefined) return payload.result;
    if (payload.final_output !== undefined) return payload.final_output;
    if (
        payload.message !== undefined ||
        payload.response !== undefined ||
        payload.content !== undefined ||
        payload.final_cards !== undefined ||
        payload.metadata !== undefined
    ) {
        return payload;
    }
    return undefined;
}

export function mapWireEventToDomainEvent(input: WireEventInput): DomainEventMapResult {
    const { eventType, payload, fallbackWorkflowId, fallbackSessionId, at, eventId } = input;
    const workflowId = resolveWorkflowId(payload, fallbackWorkflowId);
    const sessionId = resolveSessionId(payload, fallbackSessionId);
    const runId = resolveRunId(payload);
    if (!workflowId) {
        return { ok: false, reason: "missing_workflow_id", details: eventType };
    }
    if (!runId) {
        return { ok: false, reason: "invalid_payload", details: "missing run_id" };
    }

    if (eventType === "WORKFLOW_STARTED") {
        return { ok: true, event: { kind: "workflow.started", workflowId, sessionId, at, runId } };
    }
    if (eventType === "WORKFLOW_COMPLETED") {
        return {
            ok: true,
            event: {
                kind: "workflow.completed",
                workflowId,
                sessionId,
                at,
                runId,
                result: terminalResultPayload(payload),
            },
        };
    }
    if (eventType === "done" || eventType === "STREAM_END") {
        return {
            ok: true,
            event: {
                kind: "timeline.event",
                workflowId,
                eventId,
                eventKind: eventType,
                streamId: asString(payload.stream_id) || undefined,
                payload,
                at,
                message: asString(payload.message) || undefined,
                agentId: asString(payload.agent_id) || undefined,
                seq: asNumber(payload.seq),
                runId,
            },
        };
    }
    if (eventType === "WORKFLOW_FAILED" || eventType === "error") {
        const message = asString(payload.message) || "workflow failed";
        const reasonCode = asString(payload.code) || asString(payload.error_code) || "INTERNAL";
        return {
            ok: true,
            event: {
                kind: "workflow.failed",
                workflowId,
                sessionId,
                at,
                runId,
                reasonCode,
                message,
            },
        };
    }
    if (eventType === "thread.message.delta") {
        const delta = typeof payload.delta === "string" && payload.delta.length > 0
            ? payload.delta
            : null;
        if (!delta) {
            return { ok: false, reason: "invalid_payload", details: "missing delta" };
        }
        return {
            ok: true,
            event: {
                kind: "message.delta",
                workflowId,
                messageId: asString(payload.stream_id) || eventId,
                delta,
                seq: asNumber(payload.seq),
                at,
                runId,
            },
        };
    }
    if (eventType === "thread.message.completed") {
        const content = normalizeCompletedContent(payload);
        if (!content.trim()) {
            return { ok: false, reason: "unsupported_empty_message", details: "empty completed content" };
        }
        const metadata = payload.metadata && typeof payload.metadata === "object"
            ? (payload.metadata as Record<string, unknown>)
            : undefined;
        return {
            ok: true,
            event: {
                kind: "message.completed",
                workflowId,
                messageId: asString(payload.stream_id) || eventId,
                content,
                metadata,
                at,
                runId,
            },
        };
    }
    if (eventType === "LLM_OUTPUT") {
        const content = normalizeCompletedContent(payload);
        if (!content.trim()) {
            return {
                ok: true,
                event: {
                    kind: "timeline.event",
                    workflowId,
                    eventId,
                    eventKind: eventType,
                    streamId: asString(payload.stream_id) || undefined,
                    payload: payload.payload,
                    at,
                    message: asString(payload.message) || undefined,
                    agentId: asString(payload.agent_id) || undefined,
                    seq: asNumber(payload.seq),
                    runId,
                },
            };
        }
        return {
            ok: true,
            event: {
                kind: "message.completed",
                workflowId,
                messageId: asString(payload.stream_id) || eventId,
                content,
                metadata: payload.metadata && typeof payload.metadata === "object"
                    ? (payload.metadata as Record<string, unknown>)
                    : undefined,
                at,
                runId,
            },
        };
    }
    if (eventType === "WORKFLOW_CANCELLED") {
        return { ok: true, event: { kind: "control.cancel.confirmed", taskId: workflowId, sessionId, at, runId } };
    }

    if (eventType === "WORKSPACE_UPDATED") {
        const version = typeof payload.version === "number" ? payload.version : 1;
        const cards = Array.isArray(payload.cards) ? payload.cards : [];
        return {
            ok: true,
            event: {
                kind: "workspace.updated",
                sessionId: sessionId || "unknown",
                version,
                cards,
                at,
            } as RunDomainEvent,
        };
    }

    return {
        ok: true,
        event: {
            kind: "timeline.event",
            workflowId,
            eventId,
            eventKind: eventType,
            streamId: asString(payload.stream_id) || undefined,
            payload,
            at,
            message: asString(payload.message) || undefined,
            agentId: asString(payload.agent_id) || undefined,
            seq: asNumber(payload.seq),
            runId,
        },
    };
}

const EVENT_TYPES: EventType[] = [
    "thread.message.delta",
    "thread.message.completed",
    "error",
    "done",
    "STREAM_END",
    "WORKFLOW_FAILED",
    "workflow.pausing",
    "workflow.resuming",
    "workflow.cancelling",
    "ROLE_ASSIGNED",
    "TEAM_RECRUITED",
    "TEAM_RETIRED",
    "TEAM_STATUS",
    "DELEGATION",
    "BUDGET_THRESHOLD",
    "TOOL_INVOKED",
    "TOOL_OBSERVATION",
    "WORKFLOW_STARTED",
    "WORKFLOW_PROGRESS",
    "WORKFLOW_WAITING_INPUT",
    "WORKFLOW_PAUSED",
    "WORKFLOW_RESUMED",
    "WORKFLOW_CANCELLING",
    "WORKFLOW_COMPLETED",
    "WORKFLOW_CANCELLED",
    "AGENT_STARTED",
    "AGENT_COMPLETED",
    "AGENT_THINKING",
    "LLM_PROMPT",
    "LLM_OUTPUT",
    "LLM_PARTIAL",
    "LLM_USAGE_RECORDED",
    "DATA_PROCESSING",
    "PROGRESS",
    "LANGGRAPH_PROGRESS",
    "SYNTHESIS",
    "REFLECTION",
    "WAITING",
    "APPROVAL_REQUESTED",
    "APPROVAL_DECISION",
    "DEPENDENCY_SATISFIED",
    "ERROR_OCCURRED",
    "ERROR_RECOVERY",
    "MESSAGE_SENT",
    "MESSAGE_RECEIVED",
    "WORKSPACE_UPDATED",
    "STATUS_UPDATE",
    "NODE_STARTED",
    "NODE_COMPLETED",
    "NODE_FAILED",
];

const EVENT_TYPE_SET = new Set<string>(EVENT_TYPES);

function asEventType(value: string): EventType | null {
    if (EVENT_TYPE_SET.has(value)) return value as EventType;
    return null;
}

export function projectDomainEventToRunEvent(event: RunDomainEvent): RunEvent | null {
    if (event.kind === "workflow.started") {
        return { type: "WORKFLOW_STARTED", workflow_id: event.workflowId, run_id: event.runId || undefined, timestamp: event.at };
    }
    if (event.kind === "workflow.completed") {
        return { type: "WORKFLOW_COMPLETED", workflow_id: event.workflowId, run_id: event.runId || undefined, timestamp: event.at };
    }
    if (event.kind === "workflow.failed") {
        return {
            type: "WORKFLOW_FAILED",
            workflow_id: event.workflowId,
            run_id: event.runId || undefined,
            timestamp: event.at,
            message: event.message,
            error_code: event.reasonCode,
        };
    }
    if (event.kind === "message.delta") {
        return {
            type: "thread.message.delta",
            workflow_id: event.workflowId,
            run_id: event.runId || undefined,
            stream_id: event.messageId,
            timestamp: event.at,
            delta: event.delta,
            seq: event.seq,
        };
    }
    if (event.kind === "message.completed") {
        return {
            type: "thread.message.completed",
            workflow_id: event.workflowId,
            run_id: event.runId || undefined,
            stream_id: event.messageId,
            timestamp: event.at,
            content: event.content,
            metadata: event.metadata,
        };
    }
    if (event.kind === "timeline.event") {
        const type = asEventType(event.eventKind);
        if (!type) return null;
        return {
            type,
            id: asNumber(event.eventId),
            workflow_id: event.workflowId,
            run_id: event.runId || undefined,
            stream_id: event.streamId || event.eventId,
            timestamp: event.at,
            payload: event.payload,
            message: event.message,
            agent_id: event.agentId,
            seq: event.seq,
        } as RunEvent;
    }
    if (event.kind === "control.cancel.confirmed") {
        return { type: "WORKFLOW_CANCELLED", workflow_id: event.taskId, run_id: event.runId || undefined, timestamp: event.at };
    }
    if (event.kind === "control.rejected") {
        return {
            type: "error",
            workflow_id: event.taskId,
            run_id: event.runId || undefined,
            timestamp: event.at,
            message: event.message,
            code: event.code,
        };
    }
    if (event.kind === "workspace.updated") {
        return {
            type: "WORKSPACE_UPDATED",
            workflow_id: `session:${event.sessionId}`,
            timestamp: event.at,
            payload: {
                version: event.version,
                card_count: event.cards.length,
            },
            message: `Workspace updated (${event.cards.length} cards)`,
        };
    }
    return null;
}

export function mapControlErrorToDomainEvent(input: {
    taskId: string;
    sessionId: string | null;
    message: string;
    code?: string | null;
    runId?: string | null;
    at?: string;
}): RunDomainEvent {
    return {
        kind: "control.rejected",
        taskId: input.taskId,
        sessionId: input.sessionId,
        runId: input.runId || null,
        code: normalizeControlErrorCode(input.code || null),
        message: input.message,
        at: input.at || new Date().toISOString(),
    };
}

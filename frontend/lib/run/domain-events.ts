import { EventType, RunEvent } from "@/lib/kardcraft/types";
import { CardData } from "./types";

export type ControlErrorCode =
    | "INVALID_TRANSITION"
    | "TASK_NOT_FOUND"
    | "SESSION_MISMATCH"
    | "AUTHZ_DENIED"
    | "CONFLICT"
    | "TIMEOUT"
    | "TRANSPORT_UNAVAILABLE"
    | "INTERNAL";

export type RunDomainEvent =
    | {
          kind: "task.created";
          taskId: string;
          sessionId: string;
          query: string;
          createdAt: string;
      }
    | {
          kind: "workflow.started";
          workflowId: string;
          sessionId: string | null;
          at: string;
      }
    | {
          kind: "workflow.completed";
          workflowId: string;
          sessionId: string | null;
          at: string;
          result?: unknown;
      }
    | {
          kind: "workflow.failed";
          workflowId: string;
          sessionId: string | null;
          at: string;
          reasonCode: string;
          message: string;
      }
    | {
          kind: "message.delta";
          workflowId: string;
          messageId: string;
          delta: string;
          seq?: number;
          at: string;
      }
    | {
          kind: "message.completed";
          workflowId: string;
          messageId: string;
          content: string;
          metadata?: Record<string, unknown>;
          at: string;
      }
    | {
          kind: "timeline.event";
          workflowId: string;
          eventId: string;
          eventKind: string;
          payload?: unknown;
          at: string;
          message?: string;
          agentId?: string;
          seq?: number;
      }
    | {
          kind: "workspace.updated";
          sessionId: string;
          version: number;
          cards: CardData[];
          at: string;
      }
    | {
          kind: "control.pause.requested";
          taskId: string;
          sessionId: string | null;
          at: string;
      }
    | {
          kind: "control.resume.requested";
          taskId: string;
          sessionId: string | null;
          at: string;
      }
    | {
          kind: "control.cancel.requested";
          taskId: string;
          sessionId: string | null;
          at: string;
      }
    | {
          kind: "control.pause.confirmed";
          taskId: string;
          sessionId: string | null;
          at: string;
      }
    | {
          kind: "control.resume.confirmed";
          taskId: string;
          sessionId: string | null;
          at: string;
      }
    | {
          kind: "control.cancel.confirmed";
          taskId: string;
          sessionId: string | null;
          at: string;
      }
    | {
          kind: "control.rejected";
          taskId: string;
          sessionId: string | null;
          code: ControlErrorCode;
          message: string;
          at: string;
      };

export type DomainEventRejectReason =
    | "invalid_payload"
    | "unknown_type"
    | "missing_workflow_id"
    | "unsupported_empty_message";

export type DomainEventMapResult =
    | { ok: true; event: RunDomainEvent }
    | { ok: false; reason: DomainEventRejectReason; details?: string };

type WireEventInput = {
    eventType: string;
    payload: Record<string, unknown>;
    fallbackWorkflowId: string;
    fallbackSessionId?: string | null;
    at: string;
    eventId: string;
};

const TIMELINE_EVENT_TYPES = new Set<string>([
    "WORKFLOW_PROGRESS",
    "NODE_STARTED",
    "NODE_COMPLETED",
    "NODE_FAILED",
    "LANGGRAPH_PROGRESS",
    "AGENT_THINKING",
    "AGENT_STARTED",
    "AGENT_COMPLETED",
    "LLM_PROMPT",
    "LLM_OUTPUT",
    "PROGRESS",
    "DELEGATION",
    "DATA_PROCESSING",
    "TOOL_INVOKED",
    "TOOL_OBSERVATION",
    "SYNTHESIS",
    "REFLECTION",
    "ROLE_ASSIGNED",
    "TEAM_RECRUITED",
    "TEAM_RETIRED",
    "TEAM_STATUS",
    "WAITING",
    "ERROR_RECOVERY",
    "ERROR_OCCURRED",
    "BUDGET_THRESHOLD",
    "DEPENDENCY_SATISFIED",
    "APPROVAL_REQUESTED",
    "APPROVAL_DECISION",
    "MESSAGE_SENT",
    "MESSAGE_RECEIVED",
    "WORKSPACE_UPDATED",
    "STATUS_UPDATE",
    "workflow.pausing",
    "workflow.resuming",
    "workflow.cancelling",
]);

const KNOWN_EVENT_TYPES = new Set<string>([
    "thread.message.delta",
    "thread.message.completed",
    "WORKFLOW_STARTED",
    "WORKFLOW_COMPLETED",
    "WORKFLOW_FAILED",
    "WORKFLOW_CANCELLED",
    "workflow.started",
    "workflow.completed",
    "workflow.failed",
    "workflow.paused",
    "workflow.resuming",
    "workflow.resumed",
    "workflow.cancelled",
    "error",
    "done",
    "STREAM_END",
    ...TIMELINE_EVENT_TYPES,
]);

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
    return "";
}

export function mapWireEventToDomainEvent(input: WireEventInput): DomainEventMapResult {
    const { eventType, payload, fallbackWorkflowId, fallbackSessionId, at, eventId } = input;
    if (!KNOWN_EVENT_TYPES.has(eventType)) {
        return { ok: false, reason: "unknown_type", details: eventType };
    }

    const workflowId = resolveWorkflowId(payload, fallbackWorkflowId);
    const sessionId = resolveSessionId(payload, fallbackSessionId);
    if (!workflowId) {
        return { ok: false, reason: "missing_workflow_id", details: eventType };
    }

    if (eventType === "WORKFLOW_STARTED" || eventType === "workflow.started") {
        return { ok: true, event: { kind: "workflow.started", workflowId, sessionId, at } };
    }
    if (eventType === "WORKFLOW_COMPLETED" || eventType === "workflow.completed" || eventType === "done" || eventType === "STREAM_END") {
        return {
            ok: true,
            event: {
                kind: "workflow.completed",
                workflowId,
                sessionId,
                at,
                result: payload.result ?? payload.final_output,
            },
        };
    }
    if (eventType === "WORKFLOW_FAILED" || eventType === "workflow.failed" || eventType === "error") {
        const message = asString(payload.message) || "workflow failed";
        const reasonCode = asString(payload.code) || asString(payload.error_code) || "INTERNAL";
        return {
            ok: true,
            event: {
                kind: "workflow.failed",
                workflowId,
                sessionId,
                at,
                reasonCode,
                message,
            },
        };
    }
    if (eventType === "thread.message.delta") {
        const delta = asString(payload.delta);
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
            },
        };
    }
    if (eventType === "workflow.pausing") {
        return { ok: true, event: { kind: "control.pause.requested", taskId: workflowId, sessionId, at } };
    }
    if (eventType === "workflow.resuming") {
        return { ok: true, event: { kind: "control.resume.requested", taskId: workflowId, sessionId, at } };
    }
    if (eventType === "workflow.cancelling") {
        return { ok: true, event: { kind: "control.cancel.requested", taskId: workflowId, sessionId, at } };
    }
    if (eventType === "workflow.paused") {
        return { ok: true, event: { kind: "control.pause.confirmed", taskId: workflowId, sessionId, at } };
    }
    if (eventType === "workflow.resumed") {
        return { ok: true, event: { kind: "control.resume.confirmed", taskId: workflowId, sessionId, at } };
    }
    if (eventType === "workflow.cancelled" || eventType === "WORKFLOW_CANCELLED") {
        return { ok: true, event: { kind: "control.cancel.confirmed", taskId: workflowId, sessionId, at } };
    }

    return {
        ok: true,
        event: {
            kind: "timeline.event",
            workflowId,
            eventId,
            eventKind: eventType,
            payload: payload.payload,
            at,
            message: asString(payload.message) || undefined,
            agentId: asString(payload.agent_id) || undefined,
            seq: asNumber(payload.seq),
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
    "workflow.paused",
    "workflow.resumed",
    "workflow.cancelling",
    "workflow.cancelled",
    "ROLE_ASSIGNED",
    "TEAM_RECRUITED",
    "TEAM_RETIRED",
    "TEAM_STATUS",
    "DELEGATION",
    "BUDGET_THRESHOLD",
    "TOOL_INVOKED",
    "TOOL_OBSERVATION",
    "WORKFLOW_STARTED",
    "WORKFLOW_COMPLETED",
    "AGENT_STARTED",
    "AGENT_COMPLETED",
    "AGENT_THINKING",
    "LLM_PROMPT",
    "LLM_OUTPUT",
    "DATA_PROCESSING",
    "PROGRESS",
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
        return { type: "WORKFLOW_STARTED", workflow_id: event.workflowId, timestamp: event.at };
    }
    if (event.kind === "workflow.completed") {
        return { type: "WORKFLOW_COMPLETED", workflow_id: event.workflowId, timestamp: event.at };
    }
    if (event.kind === "workflow.failed") {
        return {
            type: "WORKFLOW_FAILED",
            workflow_id: event.workflowId,
            timestamp: event.at,
            message: event.message,
            error_code: event.reasonCode,
        };
    }
    if (event.kind === "message.delta") {
        return {
            type: "thread.message.delta",
            workflow_id: event.workflowId,
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
            workflow_id: event.workflowId,
            stream_id: event.eventId,
            timestamp: event.at,
            payload: event.payload,
            message: event.message,
            agent_id: event.agentId,
            seq: event.seq,
        } as RunEvent;
    }
    if (event.kind === "control.pause.requested") {
        return { type: "workflow.pausing", workflow_id: event.taskId, timestamp: event.at };
    }
    if (event.kind === "control.resume.requested") {
        return { type: "workflow.resuming", workflow_id: event.taskId, timestamp: event.at };
    }
    if (event.kind === "control.cancel.requested") {
        return { type: "workflow.cancelling", workflow_id: event.taskId, timestamp: event.at };
    }
    if (event.kind === "control.pause.confirmed") {
        return { type: "workflow.paused", workflow_id: event.taskId, timestamp: event.at };
    }
    if (event.kind === "control.resume.confirmed") {
        return { type: "workflow.resumed", workflow_id: event.taskId, timestamp: event.at };
    }
    if (event.kind === "control.cancel.confirmed") {
        return { type: "workflow.cancelled", workflow_id: event.taskId, timestamp: event.at };
    }
    if (event.kind === "control.rejected") {
        return {
            type: "error",
            workflow_id: event.taskId,
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
    at?: string;
}): RunDomainEvent {
    return {
        kind: "control.rejected",
        taskId: input.taskId,
        sessionId: input.sessionId,
        code: normalizeControlErrorCode(input.code || null),
        message: input.message,
        at: input.at || new Date().toISOString(),
    };
}

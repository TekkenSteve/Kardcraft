"use client";

import { getStreamUrlForWorkflows } from "@/lib/kardcraft/api";
import { RunDomainEvent, mapWireEventToDomainEvent } from "@/lib/run/domain-events";
import { RuntimeEnvelope, validateRuntimeEnvelope } from "@/lib/run/runtime-envelope";
import { CardData } from "@/lib/run/types";
import { logError } from "@/lib/observability/client";

type ConnectionState = "idle" | "connecting" | "connected" | "reconnecting" | "error";

type SubscriptionHandlers = {
    onConnectionState: (value: ConnectionState) => void;
    onStreamError: (value: string | null) => void;
    onDomainEvent: (event: RunDomainEvent) => void;
    onCardsBatch: (cards: CardData[]) => void;
    onEnvelope?: (envelope: RuntimeEnvelope) => void;
};

type Subscription = {
    id: string;
    workflowId: string;
    sessionId: string | null;
    handlers: SubscriptionHandlers;
};

const MAX_RECONNECT_DELAY_MS = 10000;
const BASE_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_ATTEMPTS = 8;
const MAX_HANDLED_EVENT_IDS = 5000;

const KNOWN_EVENT_TYPES = [
    "thread.message.delta",
    "thread.message.completed",
    "WORKFLOW_STARTED",
    "WORKFLOW_COMPLETED",
    "WORKFLOW_FAILED",
    "WORKFLOW_CANCELLED",
    "workflow.completed",
    "workflow.failed",
    "workflow.cancelled",
    "WORKFLOW_PROGRESS",
    "NODE_STARTED",
    "NODE_COMPLETED",
    "NODE_FAILED",
    "LANGGRAPH_PROGRESS",
    "workflow.pausing",
    "workflow.resuming",
    "workflow.paused",
    "workflow.resumed",
    "workflow.cancelling",
    "AGENT_THINKING",
    "AGENT_STARTED",
    "AGENT_COMPLETED",
    "LLM_PROMPT",
    "LLM_OUTPUT",
    "LLM_PARTIAL",
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
    "CARD_UPDATED",
    "error",
    "done",
    "STREAM_END",
] as const;

function asCardData(data: Record<string, unknown>): CardData | null {
    const cardId = typeof data.card_id === "string" ? data.card_id : typeof data.id === "string" ? data.id : "";
    if (!cardId) return null;
    return {
        id: typeof data.id === "string" ? data.id : cardId,
        user_id: typeof data.user_id === "string" ? data.user_id : "system",
        card_id: cardId,
        content: (data.content as CardData["content"]) || {
            version: 1,
            model: "mcq",
            data: { front: "", back: "" },
            media: [],
        },
        edit_state: (data.edit_state as CardData["edit_state"]) || { status: "draft" },
        concepts: Array.isArray(data.concepts) ? (data.concepts as string[]) : [],
        meta: (data.meta as CardData["meta"]) || {
            created_at: new Date(0).toISOString(),
            modified_at: new Date(0).toISOString(),
            manual_edits: 0,
        },
        deleted_at: typeof data.deleted_at === "string" ? data.deleted_at : undefined,
    };
}

export class SseGateway {
    private source: EventSource | null = null;
    private state: ConnectionState = "idle";
    private streamError: string | null = null;
    private subscriptions = new Map<string, Subscription>();
    private handledEventIds = new Set<string>();
    private attempt = 0;
    private reconnectTimer: number | null = null;
    private lastUrl = "";

    private reportProtocolViolation(payload: {
        reason: string;
        explicitType?: string;
        workflowId?: string;
        runId?: string;
        sessionId?: string;
        eventId?: string;
    }): void {
        logError("runtime_sse_envelope_rejected", {
            reason: payload.reason,
            explicit_type: payload.explicitType || null,
            workflow_id: payload.workflowId || null,
            run_id: payload.runId || null,
            session_id: payload.sessionId || null,
            event_id: payload.eventId || null,
        });
    }

    subscribe(workflowId: string, sessionId: string | null, handlers: SubscriptionHandlers): () => void {
        const id = `${workflowId}:${sessionId || "_"}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
        this.subscriptions.set(id, { id, workflowId, sessionId, handlers });
        this.syncConnection();
        handlers.onConnectionState(this.state);
        handlers.onStreamError(this.streamError);

        return () => {
            this.subscriptions.delete(id);
            this.syncConnection();
        };
    }

    retry(): void {
        if (this.reconnectTimer != null) {
            window.clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        this.attempt = 0;
        this.syncConnection(true);
    }

    private notifyConnectionState(value: ConnectionState): void {
        this.state = value;
        for (const sub of this.subscriptions.values()) {
            sub.handlers.onConnectionState(value);
        }
    }

    private notifyStreamError(value: string | null): void {
        this.streamError = value;
        for (const sub of this.subscriptions.values()) {
            sub.handlers.onStreamError(value);
        }
    }

    private workflowIds(): string[] {
        return Array.from(new Set(Array.from(this.subscriptions.values()).map((item) => item.workflowId)));
    }

    private closeSource(): void {
        if (this.source) {
            this.source.close();
            this.source = null;
        }
    }

    private syncConnection(forceReconnect: boolean = false): void {
        const workflowIds = this.workflowIds();
        if (workflowIds.length === 0) {
            this.closeSource();
            this.notifyConnectionState("idle");
            this.notifyStreamError(null);
            this.lastUrl = "";
            this.handledEventIds.clear();
            return;
        }

        const nextUrl = getStreamUrlForWorkflows(workflowIds);
        if (!forceReconnect && this.source && this.lastUrl === nextUrl) return;

        this.closeSource();
        this.lastUrl = nextUrl;
        this.notifyStreamError(null);
        this.notifyConnectionState(this.attempt > 0 ? "reconnecting" : "connecting");

        const source = new EventSource(nextUrl, { withCredentials: true });
        this.source = source;

        source.onopen = () => {
            this.attempt = 0;
            this.notifyConnectionState("connected");
            this.notifyStreamError(null);
        };
        source.onerror = () => {
            this.closeSource();
            this.attempt += 1;
            if (this.attempt > MAX_RECONNECT_ATTEMPTS) {
                this.notifyConnectionState("error");
                this.notifyStreamError(`Stream unavailable after ${this.attempt} attempts`);
                return;
            }
            this.notifyConnectionState("reconnecting");
            this.notifyStreamError(null);
            const delay = Math.min(BASE_RECONNECT_DELAY_MS * Math.pow(2, this.attempt - 1), MAX_RECONNECT_DELAY_MS);
            this.reconnectTimer = window.setTimeout(() => {
                this.reconnectTimer = null;
                this.syncConnection(true);
            }, delay);
        };

        const handleEvent = (payload: MessageEvent, explicitType?: string) => {
            if (!payload?.data || payload.data === "undefined" || payload.data === "[DONE]") return;
            try {
                const parsed = JSON.parse(payload.data) as unknown;
                const validated = validateRuntimeEnvelope(parsed);
                if (!validated.ok) {
                    const raw = parsed as Record<string, unknown>;
                    this.reportProtocolViolation({
                        reason: validated.reason,
                        explicitType,
                        workflowId: typeof raw?.workflow_id === "string" ? raw.workflow_id : undefined,
                        runId: typeof raw?.run_id === "string" ? raw.run_id : undefined,
                        sessionId: typeof raw?.session_id === "string" ? raw.session_id : undefined,
                        eventId: typeof raw?.event_id === "string" ? raw.event_id : undefined,
                    });
                    return;
                }
                const envelope = validated.value;
                if (this.handledEventIds.has(envelope.event_id)) return;
                this.handledEventIds.add(envelope.event_id);
                if (this.handledEventIds.size > MAX_HANDLED_EVENT_IDS) {
                    const first = this.handledEventIds.values().next().value;
                    if (first) this.handledEventIds.delete(first);
                }

                const eventType = explicitType || envelope.event_type;
                const interested = Array.from(this.subscriptions.values()).filter(
                    (item) => item.workflowId === envelope.workflow_id && (!item.sessionId || item.sessionId === envelope.session_id),
                );
                if (interested.length === 0) return;
                interested.forEach((sub) => sub.handlers.onEnvelope?.(envelope));

                if (eventType === "CARD_UPDATED") {
                    const card = asCardData(envelope.payload);
                    if (card) {
                        interested.forEach((sub) => sub.handlers.onCardsBatch([card]));
                    }
                    return;
                }

                const mapped = mapWireEventToDomainEvent({
                    eventType,
                    payload: {
                        ...envelope.payload,
                        workflow_id: envelope.workflow_id,
                        run_id: envelope.run_id,
                        session_id: envelope.session_id,
                        event_id: envelope.event_id,
                        correlation_id: envelope.correlation_id,
                    },
                    fallbackWorkflowId: envelope.workflow_id,
                    fallbackSessionId: envelope.session_id,
                    at: envelope.occurred_at,
                    eventId: envelope.event_id,
                });
                if (!mapped.ok) {
                    this.reportProtocolViolation({
                        reason: `domain_map_rejected:${mapped.reason}`,
                        explicitType: eventType,
                        workflowId: envelope.workflow_id,
                        runId: envelope.run_id,
                        sessionId: envelope.session_id,
                        eventId: envelope.event_id,
                    });
                    return;
                }
                interested.forEach((sub) => sub.handlers.onDomainEvent(mapped.event));
            } catch (error) {
                this.reportProtocolViolation({
                    reason: "invalid_json_payload",
                    explicitType,
                });
                logError(error, {
                    area: "sse_gateway",
                    reason: "invalid_json_payload",
                });
                return;
            }
        };

        source.onmessage = (event) => handleEvent(event);
        KNOWN_EVENT_TYPES.forEach((eventType) => {
            source.addEventListener(eventType, (event) => handleEvent(event as MessageEvent, eventType));
        });
    }
}

const globalGateway = new SseGateway();
export const globalSseGateway = globalGateway;

import { assign, createMachine } from "xstate";
import { mapWireEventToDomainEvent, RunDomainEvent } from "./domain-events";
import { CardData } from "./types";

const MAX_RECONNECT_DELAY_MS = 10000;
const BASE_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_ATTEMPTS = 8;
const MAX_HANDLED_EVENT_KEYS = 2000;

const STREAM_EVENT_TYPES = [
    "thread.message.delta",
    "thread.message.completed",
    "WORKFLOW_STARTED",
    "WORKFLOW_COMPLETED",
    "WORKFLOW_FAILED",
    "WORKFLOW_PROGRESS",
    "NODE_STARTED",
    "NODE_COMPLETED",
    "NODE_FAILED",
    "LANGGRAPH_PROGRESS",
    "workflow.pausing",
    "workflow.paused",
    "workflow.resumed",
    "workflow.cancelling",
    "workflow.cancelled",
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

type ConnectionState = "idle" | "connecting" | "connected" | "reconnecting" | "error";

export type EventSourceLike = {
    readyState: number;
    onopen: ((event: Event) => void) | null;
    onmessage: ((event: MessageEvent) => void) | null;
    onerror: ((event: Event) => void) | null;
    addEventListener: (type: string, listener: (event: Event | MessageEvent) => void) => void;
    close: () => void;
};

type StreamActorContext = {
    workflowId: string | null;
    restartKey: number;
    source: EventSourceLike | null;
    attempt: number;
    lastEventId: string | null;
    handledEventKeys: Set<string>;
    cardSnapshots: Map<string, string>;
};

type StreamActorEvent =
    | { type: "START"; workflowId: string; restartKey: number }
    | { type: "OPEN" }
    | { type: "EVENT"; payload: MessageEvent; eventType?: string }
    | { type: "ERROR"; reason: "closed" | "transport_error" }
    | { type: "RETRY" }
    | { type: "STOP" };

export type StreamActorDeps = {
    getStreamUrl: (workflowId: string) => string;
    createEventSource: (url: string) => EventSourceLike;
    nowIso: () => string;
    onConnectionState: (value: ConnectionState) => void;
    onStreamError: (value: string | null) => void;
    onDomainEvent: (event: RunDomainEvent) => void;
    onCardsBatch: (cards: CardData[]) => void;
    onRejectWireEvent?: (params: { type: string; reason: string; details?: string }) => void;
};

function resolveWorkflowId(data: Record<string, unknown>, fallbackWorkflowId: string): string {
    const fromTopLevel = typeof data.workflow_id === "string" ? data.workflow_id.trim() : "";
    if (fromTopLevel) return fromTopLevel;

    const fromTaskID = typeof data.task_id === "string" ? data.task_id.trim() : "";
    if (fromTaskID) return fromTaskID;

    const payload = data.payload;
    if (payload && typeof payload === "object") {
        const payloadRecord = payload as Record<string, unknown>;
        const nestedWorkflow = typeof payloadRecord.workflow_id === "string" ? payloadRecord.workflow_id.trim() : "";
        if (nestedWorkflow) return nestedWorkflow;
        const nestedTask = typeof payloadRecord.task_id === "string" ? payloadRecord.task_id.trim() : "";
        if (nestedTask) return nestedTask;
    }

    return fallbackWorkflowId;
}

const asCardData = (data: Record<string, unknown>): CardData | null => {
    const cardId = typeof data.card_id === "string" ? data.card_id : typeof data.id === "string" ? data.id : "";
    if (!cardId) return null;

    return {
        id: typeof data.id === "string" ? data.id : cardId,
        user_id: typeof data.user_id === "string" ? data.user_id : "system",
        card_id: cardId,
        content: (data.content as CardData["content"]) || {
            version: 1,
            model: "mcq",
            data: {
                front: "",
                back: "",
            },
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
};

const reconnectDelay = (attempt: number) => Math.min(BASE_RECONNECT_DELAY_MS * Math.pow(2, attempt), MAX_RECONNECT_DELAY_MS);
const streamUnavailableMessage = (workflowId: string, attempt: number) =>
    `Stream unavailable for workflow ${workflowId} after ${attempt} attempts`;

export function createStreamActorMachine(deps: StreamActorDeps) {
    return createMachine({
        types: {} as {
            context: StreamActorContext;
            events: StreamActorEvent;
        },
        context: {
            workflowId: null,
            restartKey: 0,
            source: null,
            attempt: 0,
            lastEventId: null,
            handledEventKeys: new Set<string>(),
            cardSnapshots: new Map<string, string>(),
        },
        initial: "idle",
        states: {
            idle: {
                entry: () => {
                    deps.onConnectionState("idle");
                },
                on: {
                    START: {
                        target: "connecting",
                        actions: assign(({ event }) => ({
                            workflowId: event.workflowId,
                            restartKey: event.restartKey,
                            attempt: 0,
                            lastEventId: null,
                            handledEventKeys: new Set<string>(),
                            cardSnapshots: new Map<string, string>(),
                        })),
                    },
                },
            },
            connecting: {
                entry: [
                    ({ context }) => {
                        if (!context.workflowId) return;
                        deps.onStreamError(null);
                        deps.onConnectionState(context.attempt > 0 ? "reconnecting" : "connecting");
                    },
                    assign(({ context, self }) => {
                        if (!context.workflowId) return {};
                        const baseUrl = deps.getStreamUrl(context.workflowId);
                        let url = baseUrl;
                        if (context.lastEventId) {
                            const urlObj = new URL(baseUrl, window.location.origin);
                            urlObj.searchParams.set("last_event_id", context.lastEventId);
                            url = urlObj.toString();
                        }
                        const source = deps.createEventSource(url);

                        source.onopen = () => {
                            self.send({ type: "OPEN" });
                        };
                        source.onmessage = (payload) => {
                            self.send({ type: "EVENT", payload });
                        };
                        source.onerror = () => {
                            const reason = source.readyState === 2 ? "closed" : "transport_error";
                            self.send({ type: "ERROR", reason });
                        };

                        STREAM_EVENT_TYPES.forEach((eventType) => {
                            source.addEventListener(eventType, (event: Event | MessageEvent) => {
                                self.send({ type: "EVENT", payload: event as MessageEvent, eventType });
                            });
                        });

                        return { source };
                    }),
                ],
                on: {
                    OPEN: {
                        target: "connected",
                        actions: () => {
                            deps.onConnectionState("connected");
                        },
                    },
                    ERROR: {
                        target: "reconnecting",
                        actions: assign(({ context }) => {
                            context.source?.close();
                            return {
                                source: null,
                                attempt: context.attempt + 1,
                            };
                        }),
                    },
                    STOP: {
                        target: "idle",
                        actions: assign(({ context }) => {
                            context.source?.close();
                            return { source: null };
                        }),
                    },
                },
            },
            connected: {
                on: {
                    EVENT: {
                        actions: assign(({ context, event }) => {
                            const messageEvent = event.payload;
                            if (!messageEvent?.data || messageEvent.data === "undefined" || messageEvent.data === "[DONE]") {
                                return {};
                            }

                            try {
                                const data = JSON.parse(messageEvent.data) as Record<string, unknown>;
                                const finalType = event.eventType || (typeof data.type === "string" ? data.type : "UNKNOWN");

                                if (!context.workflowId) {
                                    return {};
                                }

                                const normalizedWorkflowId = resolveWorkflowId(data, context.workflowId);
                                const candidateId =
                                    (data.stream_id as string | undefined) ||
                                    messageEvent.lastEventId ||
                                    (typeof data.seq === "number" ? String(data.seq) : undefined) ||
                                    (typeof data.id === "string" ? data.id : undefined);
                                const eventKey = `${finalType}:${candidateId || messageEvent.data}`;
                                if (context.handledEventKeys.has(eventKey)) {
                                    return {};
                                }
                                context.handledEventKeys.add(eventKey);
                                if (context.handledEventKeys.size > MAX_HANDLED_EVENT_KEYS) {
                                    const firstKey = context.handledEventKeys.values().next().value;
                                    if (firstKey) context.handledEventKeys.delete(firstKey);
                                }

                                const at = deps.nowIso();
                                const nextLastEventId = candidateId ? String(candidateId) : context.lastEventId;

                                if (finalType === "done" || finalType === "STREAM_END") {
                                    deps.onConnectionState("idle");
                                    context.source?.close();
                                    return {
                                        source: null,
                                        lastEventId: nextLastEventId,
                                    };
                                }

                                if (finalType === "CARD_UPDATED") {
                                    const cardId = typeof data.card_id === "string" ? data.card_id : typeof data.id === "string" ? data.id : "";
                                    if (!cardId) {
                                        return { lastEventId: nextLastEventId };
                                    }
                                    const snapshot = JSON.stringify({
                                        card_id: data.card_id,
                                        content: data.content,
                                        edit_state: data.edit_state,
                                        concepts: data.concepts,
                                        meta: data.meta,
                                        deleted_at: data.deleted_at,
                                    });
                                    const previousSnapshot = context.cardSnapshots.get(cardId);
                                    if (previousSnapshot === snapshot) {
                                        return { lastEventId: nextLastEventId };
                                    }
                                    context.cardSnapshots.set(cardId, snapshot);
                                    const card = asCardData(data);
                                    if (card) {
                                        deps.onCardsBatch([card]);
                                    }
                                    return { lastEventId: nextLastEventId };
                                }

                                const mapped = mapWireEventToDomainEvent({
                                    eventType: finalType,
                                    payload: {
                                        ...data,
                                        workflow_id: normalizedWorkflowId,
                                        task_id: typeof data.task_id === "string" ? data.task_id : normalizedWorkflowId,
                                    },
                                    fallbackWorkflowId: normalizedWorkflowId,
                                    at,
                                    eventId: String(candidateId || `${finalType}:${at}`),
                                });

                                if (!mapped.ok) {
                                    deps.onRejectWireEvent?.({
                                        type: finalType,
                                        reason: mapped.reason,
                                        details: mapped.details,
                                    });
                                    return { lastEventId: nextLastEventId };
                                }

                                deps.onDomainEvent(mapped.event);
                                return { lastEventId: nextLastEventId };
                            } catch {
                                return {};
                            }
                        }),
                    },
                    ERROR: {
                        target: "reconnecting",
                        actions: assign(({ context }) => {
                            context.source?.close();
                            return {
                                source: null,
                                attempt: context.attempt + 1,
                            };
                        }),
                    },
                    STOP: {
                        target: "idle",
                        actions: assign(({ context }) => {
                            context.source?.close();
                            return { source: null };
                        }),
                    },
                },
            },
            reconnecting: {
                entry: ({ context }) => {
                    if (!context.workflowId) return;
                    deps.onConnectionState("reconnecting");
                    deps.onStreamError(null);
                },
                always: [
                    {
                        guard: ({ context }) => context.attempt > MAX_RECONNECT_ATTEMPTS,
                        target: "failure",
                    },
                ],
                after: {
                    RECONNECT_BACKOFF: {
                        target: "connecting",
                    },
                },
                on: {
                    STOP: {
                        target: "idle",
                        actions: assign(({ context }) => {
                            context.source?.close();
                            return { source: null };
                        }),
                    },
                },
            },
            failure: {
                entry: ({ context }) => {
                    deps.onConnectionState("error");
                    if (!context.workflowId) return;
                    deps.onStreamError(streamUnavailableMessage(context.workflowId, context.attempt));
                },
                on: {
                    START: {
                        target: "connecting",
                        actions: assign(({ event }) => ({
                            workflowId: event.workflowId,
                            restartKey: event.restartKey,
                            attempt: 0,
                            lastEventId: null,
                            handledEventKeys: new Set<string>(),
                            cardSnapshots: new Map<string, string>(),
                        })),
                    },
                    STOP: {
                        target: "idle",
                    },
                },
            },
        },
    }, {
        delays: {
            RECONNECT_BACKOFF: ({ context }) => reconnectDelay(Math.max(0, context.attempt - 1)),
        },
    });
}

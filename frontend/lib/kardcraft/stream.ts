"use client";

import { useEffect, useRef } from "react";
import { getStreamUrl } from "./api";
import { useDispatch } from "react-redux";
import { setConnectionState, setStreamError } from "../features/runSlice";

const MAX_RECONNECT_DELAY_MS = 10000;
const BASE_RECONNECT_DELAY_MS = 1000;
const MAX_HANDLED_EVENT_KEYS = 2000;
const isDev = process.env.NODE_ENV !== "production";

function debugLog(...args: unknown[]) {
    if (isDev) {
        console.log(...args);
    }
}

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

export function useRunStream(workflowId: string | null, restartKey: number = 0) {
    const eventSourceRef = useRef<EventSource | null>(null);
    const reconnectTimeoutRef = useRef<number | null>(null);
    const lastEventIdRef = useRef<string | null>(null);
    const shouldReconnectRef = useRef(true);
    const lastCardSnapshotRef = useRef<Map<string, string>>(new Map());
    const handledEventKeysRef = useRef<Set<string>>(new Set());
    const pendingCardsRef = useRef<Map<string, unknown>>(new Map());
    const flushCardsTimerRef = useRef<number | null>(null);
    const dispatch = useDispatch();

    useEffect(() => {
        debugLog("[useRunStream] Hook called with:", { workflowId, restartKey });

        if (!workflowId) {
            debugLog("[useRunStream] No workflowId provided, skipping connection");
            return;
        }
        shouldReconnectRef.current = true;
        handledEventKeysRef.current.clear();
        lastCardSnapshotRef.current.clear();

        const cleanupTimeout = () => {
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
                reconnectTimeoutRef.current = null;
            }
        };
        const cleanupCardFlushTimer = () => {
            if (flushCardsTimerRef.current) {
                clearTimeout(flushCardsTimerRef.current);
                flushCardsTimerRef.current = null;
            }
        };
        const flushPendingCards = () => {
            if (!pendingCardsRef.current.size) return;
            const cards = Array.from(pendingCardsRef.current.values());
            pendingCardsRef.current.clear();
            dispatch({ type: "run/upsertCardsBatch", payload: cards });
        };
        const queueCardUpdate = (card: unknown) => {
            const cardRecord = card as { card_id?: string; id?: string } | undefined;
            const cardId = cardRecord?.card_id || cardRecord?.id;
            if (!cardId) return;
            pendingCardsRef.current.set(cardId, card);
            if (flushCardsTimerRef.current) return;
            flushCardsTimerRef.current = window.setTimeout(() => {
                flushCardsTimerRef.current = null;
                flushPendingCards();
            }, 80);
        };

        const connect = (attempt: number = 0) => {
            if (!workflowId || !shouldReconnectRef.current) return;

            cleanupTimeout();
            dispatch(setStreamError(null));
            dispatch(setConnectionState(attempt > 0 ? "reconnecting" : "connecting"));

            const baseUrl = getStreamUrl(workflowId);
            const url = lastEventIdRef.current
                ? `${baseUrl}&last_event_id=${encodeURIComponent(lastEventIdRef.current)}`
                : baseUrl;

            debugLog("[useRunStream] Connecting to SSE:", url);

            const eventSource = new EventSource(url);
            eventSourceRef.current = eventSource;

            const handleEvent = (event: MessageEvent, eventType?: string) => {
                try {
                    // Skip empty or undefined data
                    if (!event.data || event.data === "undefined") {
                        return;
                    }

                    // Special case: [DONE] is sent as plain text, not JSON
                    if (event.data === "[DONE]") {
                        return;
                    }

                    const data = JSON.parse(event.data);
                    // Set the type from the SSE event name (eventType) if provided, otherwise fall back to data.type
                    const finalType = eventType || data.type;
                    const normalizedWorkflowId = resolveWorkflowId(data as Record<string, unknown>, workflowId);
                    const candidateId =
                        data?.stream_id || event.lastEventId || data?.seq?.toString() || data?.id;
                    const eventKey = `${finalType}:${candidateId || event.data}`;
                    if (handledEventKeysRef.current.has(eventKey)) {
                        return;
                    }
                    handledEventKeysRef.current.add(eventKey);
                    if (handledEventKeysRef.current.size > MAX_HANDLED_EVENT_KEYS) {
                        const firstKey = handledEventKeysRef.current.values().next().value;
                        if (firstKey) {
                            handledEventKeysRef.current.delete(firstKey);
                        }
                    }

                    const eventWithTimestamp = {
                        ...data,
                        workflow_id: normalizedWorkflowId,
                        task_id: typeof data?.task_id === "string" ? data.task_id : normalizedWorkflowId,
                        type: finalType,
                        timestamp: new Date().toISOString(),
                    };

                    // Track last event id for resume support
                    if (candidateId) {
                        lastEventIdRef.current = String(candidateId);
                    }

                    // Dispatch to Redux
                    if (finalType === "CARD_UPDATED") {
                        const cardId = data?.card_id || data?.id;
                        if (cardId) {
                            const snapshot = JSON.stringify({
                                card_id: data?.card_id,
                                content: data?.content,
                                edit_state: data?.edit_state,
                                concepts: data?.concepts,
                                meta: data?.meta,
                                deleted_at: data?.deleted_at,
                            });
                            const lastSnapshot = lastCardSnapshotRef.current.get(cardId);
                            if (lastSnapshot === snapshot) {
                                return;
                            }
                            lastCardSnapshotRef.current.set(cardId, snapshot);
                        }
                        const normalizedCard = {
                            id: data?.id || data?.card_id,
                            user_id: data?.user_id,
                            card_id: data?.card_id || data?.id,
                            content: data?.content,
                            edit_state: data?.edit_state,
                            concepts: data?.concepts || [],
                            meta: data?.meta,
                            deleted_at: data?.deleted_at,
                        };
                        queueCardUpdate(normalizedCard);
                    } else {
                        dispatch({ type: "run/addEvent", payload: eventWithTimestamp });
                    }
                    debugLog(`[Stream] Received ${finalType} event`);
                } catch (e) {
                    console.error("Failed to handle SSE event:", event.data, e);
                }
            };

            eventSource.onopen = () => {
                debugLog("[useRunStream] SSE connection opened successfully");
                dispatch(setConnectionState("connected"));
            };

            // Listen for all Kardcraft event types
            const eventTypes = [
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
                "STREAM_END"
            ];

            eventTypes.forEach(type => {
                eventSource.addEventListener(type, (event: Event | MessageEvent) => {
                    if (type === "done" || type === "STREAM_END") {
                        // Dispatch a synthetic done event to Redux
                        dispatch({
                            type: "run/addEvent",
                            payload: {
                                type: "done",
                                workflow_id: workflowId,
                                task_id: workflowId,
                                timestamp: new Date().toISOString(),
                            }
                        });
                        debugLog("Stream ended, closing connection");
                        dispatch(setConnectionState("idle"));
                        shouldReconnectRef.current = false;
                        // Close the connection
                        eventSource.close();
                    } else {
                        // Pass the event type from the SSE event field
                        handleEvent(event as MessageEvent, type);
                    }
                });
            });

            // Also listen for generic "message" events as fallback
            eventSource.onmessage = (event) => {
                handleEvent(event as MessageEvent);
            };

            eventSource.onerror = (err) => {
                console.error("SSE Error:", err);
                eventSource.close();

                if (!shouldReconnectRef.current) {
                    dispatch(setConnectionState("idle"));
                    return;
                }

                // SSE in this system is long-poll style and may reconnect periodically.
                // Treat onerror as transport churn, not a workflow failure signal.
                dispatch(setConnectionState("reconnecting"));
                dispatch(setStreamError(null));
                const delay = Math.min(
                    BASE_RECONNECT_DELAY_MS * Math.pow(2, attempt),
                    MAX_RECONNECT_DELAY_MS
                );
                reconnectTimeoutRef.current = window.setTimeout(() => connect(attempt + 1), delay);
            };
        };

        connect();

        return () => {
            shouldReconnectRef.current = false;
            cleanupTimeout();
            cleanupCardFlushTimer();
            flushPendingCards();
            if (eventSourceRef.current) {
                eventSourceRef.current.close();
                eventSourceRef.current = null;
            }
            dispatch(setConnectionState("idle"));
        };
    }, [workflowId, restartKey, dispatch]);
}

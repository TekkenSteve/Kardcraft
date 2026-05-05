"use client";

import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { RunEvent } from "@/lib/kardcraft/types";

export interface TimelineDisplayEvent {
    id: string;
    type: "agent" | "llm" | "tool" | "system";
    status: "completed" | "running" | "failed" | "cancelled" | "paused" | "pending";
    title: string;
    timestamp: string;
    details?: string;
    detailsType?: "json" | "text";
    messageId?: string;
}

const MAX_DETAIL_CHARS = 6000;

const AGENT_EVENT_TYPES = new Set<string>([
    "AGENT_STARTED",
    "AGENT_COMPLETED",
    "AGENT_THINKING",
    "DELEGATION",
    "ROLE_ASSIGNED",
    "TEAM_RECRUITED",
    "TEAM_RETIRED",
    "TEAM_STATUS",
    "WORKFLOW_PROGRESS",
    "NODE_STARTED",
    "NODE_COMPLETED",
    "NODE_FAILED",
]);

const LLM_EVENT_TYPES = new Set<string>([
    "LLM_PROMPT",
    "LLM_OUTPUT",
    "thread.message.completed",
]);

const TOOL_EVENT_TYPES = new Set<string>([
    "TOOL_INVOKED",
    "TOOL_OBSERVATION",
]);

const FAILED_EVENT_TYPES = new Set<string>([
    "ERROR_OCCURRED",
    "error",
    "TASK_FAILED",
    "TASK_CANCELLED",
    "WORKFLOW_FAILED",
    "NODE_FAILED",
]);

const RUNNING_EVENT_TYPES = new Set<string>([
    "WORKFLOW_STARTED",
    "AGENT_STARTED",
    "NODE_STARTED",
    "AGENT_THINKING",
    "WAITING",
    "APPROVAL_REQUESTED",
    "WORKFLOW_PROGRESS",
]);

const PAUSED_EVENT_TYPES = new Set<string>([
    "workflow.paused",
]);

const COMPLETED_EVENT_TYPES = new Set<string>([
    "WORKFLOW_COMPLETED",
    "AGENT_COMPLETED",
    "NODE_COMPLETED",
    "thread.message.completed",
    "TOOL_OBSERVATION",
    "APPROVAL_DECISION",
    "DEPENDENCY_SATISFIED",
    "done",
]);

const TERMINAL_EVENT_TYPES = new Set<string>([
    "WORKFLOW_COMPLETED",
    "WORKFLOW_FAILED",
    "workflow.cancelled",
    "done",
    "STREAM_END",
]);

function eventIdentity(event: RunEvent, index: number): string {
    return event.stream_id ||
        `${event.workflow_id || "unknown"}-${event.type}-${event.seq || event.timestamp || index}`;
}

function nodeLifecycleKey(event: RunEvent): string | null {
    if (event.type !== "NODE_STARTED" && event.type !== "NODE_COMPLETED" && event.type !== "NODE_FAILED") {
        return null;
    }
    const payload = "payload" in event ? event.payload : undefined;
    if (!payload || typeof payload !== "object") return null;
    const record = payload as Record<string, unknown>;
    const nodeName = typeof record.node_name === "string" && record.node_name.trim().length > 0
        ? record.node_name.trim()
        : typeof record.event_name === "string" && record.event_name.trim().length > 0
            ? record.event_name.trim()
            : "";
    if (!nodeName) return null;
    return [event.workflow_id, event.run_id || "", nodeName].join("\u0000");
}

function buildNodeStatusOverrides(events: RunEvent[]): Map<string, TimelineDisplayEvent["status"]> {
    const activeStartedByNode = new Map<string, string[]>();
    const overrides = new Map<string, TimelineDisplayEvent["status"]>();

    events.forEach((event, index) => {
        const key = nodeLifecycleKey(event);
        if (!key) return;

        if (event.type === "NODE_STARTED") {
            const active = activeStartedByNode.get(key) || [];
            active.push(eventIdentity(event, index));
            activeStartedByNode.set(key, active);
            return;
        }

        const active = activeStartedByNode.get(key) || [];
        const startedID = active.pop();
        if (active.length > 0) {
            activeStartedByNode.set(key, active);
        } else {
            activeStartedByNode.delete(key);
        }
        if (startedID) {
            overrides.set(startedID, event.type === "NODE_FAILED" ? "failed" : "completed");
        }
    });

    return overrides;
}

function stringifyPayloadForTimeline(payload: unknown): string {
    const seen = new WeakSet<object>();
    const redactedKeys = new Set([
        "messages",
        "conversation",
        "cards",
        "state",
        "workspace",
        "raw",
    ]);

    const replacer = (key: string, value: unknown): unknown => {
        if (key && redactedKeys.has(key)) {
            if (Array.isArray(value)) return `[omitted array length=${value.length}]`;
            if (value && typeof value === "object") return "[omitted object]";
        }
        if (typeof value === "string" && value.length > 1000) {
            return `${value.slice(0, 1000)}...[truncated]`;
        }
        if (value && typeof value === "object") {
            if (seen.has(value as object)) return "[circular]";
            seen.add(value as object);
        }
        return value;
    };

    let out = "";
    try {
        out = JSON.stringify(payload, replacer, 2);
    } catch {
        out = String(payload);
    }
    if (out.length > MAX_DETAIL_CHARS) {
        return `${out.slice(0, MAX_DETAIL_CHARS)}\n...[truncated]`;
    }
    return out;
}

export function useTimeline({
    runEvents,
    currentWorkflowId,
    setActiveTab,
    conversationScrollRef,
}: {
    runEvents: RunEvent[];
    currentWorkflowId: string | null;
    setActiveTab: (value: string) => void;
    conversationScrollRef: React.RefObject<HTMLDivElement | null>;
}) {
    const { t } = useTranslation();

    const categorizeEvent = useCallback((eventType: string): "agent" | "llm" | "tool" | "system" => {
        if (AGENT_EVENT_TYPES.has(eventType)) return "agent";
        if (LLM_EVENT_TYPES.has(eventType)) return "llm";
        if (TOOL_EVENT_TYPES.has(eventType)) return "tool";
        return "system";
    }, []);

    const getEventStatus = useCallback((eventType: string): "completed" | "running" | "failed" | "cancelled" | "paused" | "pending" => {
        if (FAILED_EVENT_TYPES.has(eventType)) return "failed";
        if (eventType === "workflow.cancelled") return "cancelled";
        if (PAUSED_EVENT_TYPES.has(eventType)) return "paused";
        if (RUNNING_EVENT_TYPES.has(eventType)) return "running";
        if (COMPLETED_EVENT_TYPES.has(eventType)) return "completed";
        return "completed";
    }, []);

    const extractEventDetails = (event: RunEvent): { details?: string, detailsType?: "json" | "text" } => {
        const payload = "payload" in event ? (event as { payload?: unknown }).payload : undefined;
        const message = "message" in event ? (event as { message?: string }).message : undefined;

        if (payload) {
            let payloadStr: string;
            if (typeof payload === "string") {
                const raw = payload;
                if (raw.length > 20000) {
                    payloadStr = `${raw.slice(0, MAX_DETAIL_CHARS)}...[truncated]`;
                    return {
                        details: payloadStr,
                        detailsType: "text"
                    };
                }
                try {
                    const parsed = JSON.parse(raw);
                    payloadStr = stringifyPayloadForTimeline(parsed);
                } catch {
                    payloadStr = raw.length > MAX_DETAIL_CHARS ? `${raw.slice(0, MAX_DETAIL_CHARS)}...[truncated]` : raw;
                }
            } else {
                payloadStr = stringifyPayloadForTimeline(payload);
            }

            return {
                details: payloadStr,
                detailsType: "json"
            };
        }

        if (message) {
            return {
                details: message,
                detailsType: "text",
            };
        }

        return {};
    };

    const getFriendlyTitle = useCallback((event: RunEvent): string => {
        const typeMap: Record<string, string> = {
            "WORKFLOW_STARTED": t("runDetail.timelineEvents.workflowStarted"),
            "WORKFLOW_COMPLETED": t("runDetail.timelineEvents.workflowCompleted"),
            "AGENT_STARTED": t("runDetail.timelineEvents.agentStarted"),
            "AGENT_COMPLETED": t("runDetail.timelineEvents.agentCompleted"),
            "AGENT_THINKING": t("runDetail.timelineEvents.agentThinking"),
            "TOOL_INVOKED": t("runDetail.timelineEvents.toolInvoked"),
            "TOOL_OBSERVATION": t("runDetail.timelineEvents.toolObservation"),
            "DELEGATION": t("runDetail.timelineEvents.delegation"),
            "ROLE_ASSIGNED": t("runDetail.timelineEvents.roleAssigned"),
            "TEAM_RECRUITED": t("runDetail.timelineEvents.teamRecruited"),
            "TEAM_RETIRED": t("runDetail.timelineEvents.teamRetired"),
            "TEAM_STATUS": t("runDetail.timelineEvents.teamStatus"),
            "PROGRESS": t("runDetail.timelineEvents.progress"),
            "DATA_PROCESSING": t("runDetail.timelineEvents.dataProcessing"),
            "WAITING": t("runDetail.timelineEvents.waiting"),
            "ERROR_RECOVERY": t("runDetail.timelineEvents.errorRecovery"),
            "ERROR_OCCURRED": t("runDetail.timelineEvents.errorOccurred"),
            "BUDGET_THRESHOLD": t("runDetail.timelineEvents.budgetThreshold"),
            "DEPENDENCY_SATISFIED": t("runDetail.timelineEvents.dependencySatisfied"),
            "APPROVAL_REQUESTED": t("runDetail.timelineEvents.approvalRequested"),
            "APPROVAL_DECISION": t("runDetail.timelineEvents.approvalDecision"),
            "MESSAGE_SENT": t("runDetail.timelineEvents.messageSent"),
            "MESSAGE_RECEIVED": t("runDetail.timelineEvents.messageReceived"),
            "WORKSPACE_UPDATED": t("runDetail.timelineEvents.workspaceUpdated"),
            "STATUS_UPDATE": t("runDetail.timelineEvents.statusUpdate"),
            "workflow.paused": t("runDetail.timelineEvents.workflowPaused"),
            "workflow.resuming": t("runDetail.timelineEvents.workflowResuming"),
            "workflow.resumed": t("runDetail.timelineEvents.workflowResumed"),
            "workflow.cancelled": t("runDetail.timelineEvents.workflowCancelled"),
            "WORKFLOW_PROGRESS": t("runDetail.timelineEvents.workflowProgress"),
            "NODE_STARTED": "Node started",
            "NODE_COMPLETED": "Node completed",
            "NODE_FAILED": "Node failed",
            "thread.message.completed": t("runDetail.timelineEvents.llmResponse"),
            "done": t("runDetail.timelineEvents.done"),
            "STREAM_END": t("runDetail.timelineEvents.streamEnd"),
        };

        return typeMap[event.type] || event.type;
    }, [t]);

    const timelineEvents = useMemo(() => {
        const MAX_TIMELINE_EVENTS = 300;
        const excludedEventTypes = new Set([
            "thread.message.delta",
            "thread.message.completed",
            "LLM_PROMPT",
            "LLM_OUTPUT",
            "LLM_USAGE_RECORDED",
        ]);

        const filteredRunEvents = runEvents
            .filter((event) => !excludedEventTypes.has(event.type) && event.type)
            .slice(-MAX_TIMELINE_EVENTS);

        const deduplicatedEvents = filteredRunEvents;
        const nodeStatusOverrides = buildNodeStatusOverrides(deduplicatedEvents);

        const terminalWorkflows = new Map<string, "completed" | "failed" | "cancelled">();
        runEvents.forEach((event) => {
            if (!TERMINAL_EVENT_TYPES.has(event.type)) return;
            const nextStatus: "completed" | "failed" | "cancelled" =
                event.type === "workflow.cancelled"
                    ? "cancelled"
                    : event.type === "WORKFLOW_FAILED"
                        ? "failed"
                        : "completed";
            terminalWorkflows.set(event.workflow_id, nextStatus);
        });

        return deduplicatedEvents.map((event, index): TimelineDisplayEvent => {
            const uniqueId = eventIdentity(event, index);
            const workflowTerminalStatus = terminalWorkflows.get(event.workflow_id);
            const nodeStatusOverride = nodeStatusOverrides.get(uniqueId);
            const eventStatus = workflowTerminalStatus
                ? workflowTerminalStatus
                : nodeStatusOverride || getEventStatus(event.type);

            const { details, detailsType } = extractEventDetails(event);
            const title = getFriendlyTitle(event);

            return {
                id: uniqueId,
                type: categorizeEvent(event.type),
                status: eventStatus,
                title,
                timestamp: event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : "",
                details,
                detailsType,
                messageId: event.type === "AGENT_COMPLETED" || event.type === "WORKFLOW_COMPLETED" ? `assistant-final-${currentWorkflowId}` : undefined
            };
        });
    }, [categorizeEvent, currentWorkflowId, getEventStatus, getFriendlyTitle, runEvents]);

    const scrollToMessage = (messageId: string) => {
        if (!conversationScrollRef.current) return;
        const viewport = conversationScrollRef.current.querySelector('[data-slot="scroll-area-viewport"]');
        const element = document.getElementById(`message-${messageId}`);

        if (viewport && element) {
            viewport.scrollTo({
                top: element.offsetTop - 20,
                behavior: 'smooth'
            });
            setActiveTab("conversation");
        }
    };

    return { timelineEvents, scrollToMessage };
}

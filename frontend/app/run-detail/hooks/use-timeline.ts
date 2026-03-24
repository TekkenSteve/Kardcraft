"use client";

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { RunEvent } from "@/lib/kardcraft/types";

export interface TimelineDisplayEvent {
    id: string;
    type: "agent" | "llm" | "tool" | "system";
    status: "completed" | "running" | "failed" | "pending";
    title: string;
    timestamp: string;
    details?: string;
    detailsType?: "json" | "text";
    messageId?: string;
}

const MAX_DETAIL_CHARS = 6000;

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
    currentTaskId,
    setActiveTab,
    conversationScrollRef,
}: {
    runEvents: RunEvent[];
    currentTaskId: string | null;
    setActiveTab: (value: string) => void;
    conversationScrollRef: React.RefObject<HTMLDivElement>;
}) {
    const { t } = useTranslation();
    const categorizeEvent = (eventType: string): "agent" | "llm" | "tool" | "system" => {
        if (eventType.includes("AGENT") || eventType.includes("DELEGATION") ||
            eventType.includes("TEAM") || eventType.includes("ROLE") ||
            eventType === "WORKFLOW_PROGRESS" || eventType.startsWith("NODE_")) return "agent";
        if (eventType.includes("LLM") || eventType === "thread.message.completed") return "llm";
        if (eventType.includes("TOOL")) return "tool";
        return "system";
    };

    const getEventStatus = (eventType: string): "completed" | "running" | "failed" | "pending" => {
        if (eventType === "ERROR_OCCURRED" || eventType === "error" ||
            eventType === "TASK_FAILED" || eventType === "TASK_CANCELLED" ||
            eventType === "WORKFLOW_FAILED" || eventType === "NODE_FAILED") return "failed";
        if (eventType.includes("STARTED") || eventType === "AGENT_THINKING" ||
            eventType === "WAITING" || eventType === "APPROVAL_REQUESTED" ||
            eventType === "WORKFLOW_PROGRESS") return "running";
        if (eventType.includes("COMPLETED") || eventType === "thread.message.completed" ||
            eventType.includes("OBSERVATION") || eventType === "APPROVAL_DECISION" ||
            eventType === "DEPENDENCY_SATISFIED" || eventType === "done") return "completed";
        return "completed";
    };

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
            if (message.startsWith("Thinking:")) {
                return {
                    details: message,
                    detailsType: "text"
                };
            }
        }

        return {};
    };

    const getFriendlyTitle = (event: RunEvent): string => {
        if ("message" in event && typeof event.message === "string") {
            if (event.message === "Stream connected" && event.type === "STATUS_UPDATE") {
                return t("runDetail.timelineEvents.initializingConnection");
            }

            if (event.message.startsWith("Thinking: REASON")) {
                return t("runDetail.timelineEvents.agentReasoning");
            }
            if (event.message.startsWith("Thinking: ACT")) {
                return t("runDetail.timelineEvents.agentPlanning");
            }
            if (event.message.startsWith("Thinking:")) {
                return t("runDetail.timelineEvents.agentThinking");
            }
            if (event.message.includes("Expanded query into")) {
                return t("runDetail.timelineEvents.expandedQuery");
            }
            if (event.message.includes("Refining research query")) {
                return t("runDetail.timelineEvents.refiningQuery");
            }
            if (event.message.includes("Analyzing")) {
                return event.message.split("\n")[0];
            }
            if ("payload" in event && (event as { payload?: unknown }).payload) {
                const firstLine = event.message.split("\n")[0];
                return firstLine.length > 50 ? firstLine.substring(0, 50) + "…" : firstLine;
            }
            if (event.message.length <= 60) {
                return event.message;
            }
        }

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
            "WORKFLOW_PROGRESS": t("runDetail.timelineEvents.workflowProgress"),
            "NODE_STARTED": "Node started",
            "NODE_COMPLETED": "Node completed",
            "NODE_FAILED": "Node failed",
            "thread.message.completed": t("runDetail.timelineEvents.llmResponse"),
            "done": t("runDetail.timelineEvents.done"),
            "STREAM_END": t("runDetail.timelineEvents.streamEnd"),
        };
        return typeMap[event.type] || event.type;
    };

    const timelineEvents = useMemo(() => {
        const MAX_TIMELINE_EVENTS = 300;
        const excludedEventTypes = new Set([
            "thread.message.delta",
            "thread.message.completed",
            "LLM_PROMPT",
            "LLM_OUTPUT",
        ]);

        const filteredRunEvents = runEvents
            .filter((event) => !excludedEventTypes.has(event.type) && event.type)
            .slice(-MAX_TIMELINE_EVENTS);

        const deduplicatedEvents = filteredRunEvents.reduce((acc: RunEvent[], event) => {
            if (event.type === "BUDGET_THRESHOLD") {
                const match = "message" in event && typeof event.message === "string"
                    ? event.message.match(/Task budget at ([\d.]+)%/)
                    : null;
                if (match) {
                    const currentPercent = parseFloat(match[1]);

                    const budgetEventsKept = acc.filter((e) => e.type === "BUDGET_THRESHOLD");
                    const MAX_BUDGET_EVENTS = 5;

                    if (budgetEventsKept.length === 0) {
                        acc.push(event);
                    } else if (budgetEventsKept.length < MAX_BUDGET_EVENTS) {
                        const lastBudgetEvent = budgetEventsKept[budgetEventsKept.length - 1];
                        const lastMatch = "message" in lastBudgetEvent && typeof lastBudgetEvent.message === "string"
                            ? lastBudgetEvent.message.match(/Task budget at ([\d.]+)%/)
                            : null;
                        if (lastMatch) {
                            const lastPercent = parseFloat(lastMatch[1]);
                            if (currentPercent - lastPercent >= 100) {
                                acc.push(event);
                            }
                        }
                    }
                } else {
                    acc.push(event);
                }
            } else {
                acc.push(event);
            }
            return acc;
        }, []);

        const completedWorkflows = new Set(
            runEvents
                .filter((e) => e.type === "WORKFLOW_COMPLETED")
                .map((e) => e.workflow_id)
        );

        return deduplicatedEvents.map((event, index): TimelineDisplayEvent => {
            const workflowCompleted = completedWorkflows.has(event.workflow_id);
            const eventStatus = workflowCompleted
                ? "completed"
                : getEventStatus(event.type);

            const uniqueId = event.stream_id ||
                `${event.workflow_id || 'unknown'}-${event.type}-${event.seq || event.timestamp || index}`;

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
                messageId: event.type === "AGENT_COMPLETED" || event.type === "WORKFLOW_COMPLETED" ? `assistant-final-${currentTaskId}` : undefined
            };
        });
    }, [runEvents, currentTaskId, t]);

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

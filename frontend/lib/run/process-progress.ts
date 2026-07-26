import type { RunEvent } from "@/lib/kardcraft/types";

export type ProcessProgress = {
    label: string;
    status: "running" | "completed" | "failed";
};

const NODE_EVENT_STATUS: Record<string, ProcessProgress["status"]> = {
    NODE_STARTED: "running",
    NODE_COMPLETED: "completed",
    NODE_FAILED: "failed",
};

function asNonEmptyString(value: unknown): string | null {
    if (typeof value !== "string") return null;
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
}

function humanizeNodeName(value: string): string {
    return value
        .replace(/[._-]+/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function eventLabel(event: RunEvent): string | null {
    const payload = event.payload && typeof event.payload === "object"
        ? event.payload as Record<string, unknown>
        : {};
    const nodeName =
        asNonEmptyString(payload.node_name) ||
        asNonEmptyString(payload.event_name) ||
        asNonEmptyString(payload.node_id) ||
        asNonEmptyString(payload.node);
    if (nodeName) return humanizeNodeName(nodeName);

    const message = ("message" in event ? asNonEmptyString(event.message) : null) ||
        asNonEmptyString(payload.message);
    return message;
}

export function deriveProcessProgress(
    events: readonly RunEvent[],
    currentRunId: string | null,
): ProcessProgress | null {
    let workflowFallback: ProcessProgress | null = null;

    for (let index = events.length - 1; index >= 0; index -= 1) {
        const event = events[index];
        if (currentRunId && event.run_id && event.run_id !== currentRunId) continue;

        const nodeStatus = NODE_EVENT_STATUS[event.type];
        if (nodeStatus) {
            const label = eventLabel(event);
            if (label) return { label, status: nodeStatus };
            continue;
        }

        if (!workflowFallback && event.type === "WORKFLOW_PROGRESS") {
            const label = eventLabel(event);
            if (label) workflowFallback = { label, status: "running" };
        }
    }

    return workflowFallback;
}

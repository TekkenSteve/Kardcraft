"use client";

import { createSlice, PayloadAction } from "@reduxjs/toolkit";
import {
    LlmOutputEvent,
    RunEvent,
    ThreadMessageCompletedEvent,
    ThreadMessageDeltaEvent,
    WorkflowPausedEvent,
} from "../kardcraft/types";

const debugRun = (...args: unknown[]) => {
    // Intentionally no-op: high-frequency stream logs freeze the UI.
    void args;
};

export type HistoricalEvent = RunEvent & { isHistorical?: boolean };

export interface RunMessage {
    id: string;
    role: "user" | "assistant" | "system" | "status";
    content: string;
    timestamp?: string;
    taskId?: string;
    metadata?: Record<string, unknown>;
    isStreaming?: boolean;
    isGenerating?: boolean;
    isError?: boolean;
    isCancelled?: boolean;
    eventType?: string;
    attachments?: Array<{
        fileId: string;
        filename: string;
        size: number;
        mimeType: string;
    }>;
}

type MessageAttachment = NonNullable<RunMessage["attachments"]>[number];

const normalizeAttachment = (value: unknown): MessageAttachment | null => {
    if (!value || typeof value !== "object") return null;
    const raw = value as Record<string, unknown>;
    const fileId = String(raw.fileId ?? raw.file_id ?? raw.id ?? "").trim();
    const filename = String(raw.filename ?? raw.file_name ?? raw.name ?? "").trim();
    if (!fileId || !filename) return null;
    const sizeRaw = raw.size;
    const size = typeof sizeRaw === "number" && Number.isFinite(sizeRaw) ? sizeRaw : 0;
    const mimeTypeRaw = raw.mimeType ?? raw.mime_type ?? raw.type;
    const mimeType = typeof mimeTypeRaw === "string" ? mimeTypeRaw : "application/octet-stream";
    return { fileId, filename, size, mimeType };
};

const normalizeAttachments = (value: unknown): RunMessage["attachments"] | undefined => {
    if (!Array.isArray(value)) return undefined;
    const normalized = value
        .map((item) => normalizeAttachment(item))
        .filter((item): item is MessageAttachment => item !== null);
    return normalized.length > 0 ? normalized : undefined;
};

const normalizeMessageForStore = (message: RunMessage): RunMessage => {
    const normalizedAttachments = normalizeAttachments(message.attachments);
    const nextMetadata =
        message.metadata && typeof message.metadata === "object"
            ? { ...(message.metadata as Record<string, unknown>) }
            : message.metadata;
    if (nextMetadata && typeof nextMetadata === "object") {
        const normalizedMetaAttachments = normalizeAttachments((nextMetadata as Record<string, unknown>).attachments);
        if (normalizedMetaAttachments) {
            (nextMetadata as Record<string, unknown>).attachments = normalizedMetaAttachments;
        }
        const normalizedMetaFiles = normalizeAttachments((nextMetadata as Record<string, unknown>).files);
        if (normalizedMetaFiles) {
            (nextMetadata as Record<string, unknown>).files = normalizedMetaFiles;
        }
    }
    return {
        ...message,
        attachments: normalizedAttachments,
        metadata: nextMetadata,
    };
};

export interface CardData {
    id: string;
    user_id: string;
    card_id: string;
    suggested_question_type?: string;
    content: {
        version: number;
        model: string;
        data: {
            front: string;
            back: string;
            tags?: string[];
            concepts?: string[];
        };
        media?: {
            file_id: string;
            type: string;
            url: string;
            meta?: unknown;
        }[];
    };
    edit_state: {
        status: "draft" | "ai_editing" | "user_editing" | "confirmed";
        locked_by?: string;
        locked_at?: string;
        expires_at?: string;
    };
    concepts: string[];
    meta: {
        created_at: string;
        modified_at: string;
        manual_edits: number;
    };
    deleted_at?: string;
}

interface RunState {
    events: RunEvent[];
    messages: RunMessage[]; // We'll transform events into messages
    cards: CardData[]; // Active workspace cards
    cardsVersion: number;
    runPhase: "idle" | "clearing" | "loading" | "hydrated" | "streaming" | "error";
    status: "idle" | "running" | "completed" | "failed";
    connectionState: "idle" | "connecting" | "connected" | "reconnecting" | "error";
    streamError: string | null;
    sessionTitle: string | null;
    selectedAgent: "normal" | "card_template";
    researchStrategy: "quick" | "standard" | "deep" | "academic";
    mainWorkflowId: string | null; // Track the main workflow to distinguish from sub-workflows
    // Pause/Resume/Cancel control state
    isPaused: boolean;
    pauseCheckpoint: string | null;
    pauseReason: string | null;
    isCancelling: boolean;
    isCancelled: boolean;
    templatePreflight: {
        status: "idle" | "running" | "passed" | "failed";
        templateId: string | null;
        templateVersion: number | null;
        questionTypes: string[];
        cardCount: number | null;
        checkedAt: string | null;
        message: string | null;
    };
}

const initialState: RunState = {
    events: [],
    messages: [],
    cards: [],
    cardsVersion: 0,
    runPhase: "idle",
    status: "idle",
    connectionState: "idle",
    streamError: null,
    sessionTitle: null,
    selectedAgent: "normal",
    researchStrategy: "quick",
    mainWorkflowId: null,
    // Pause/Resume/Cancel control state
    isPaused: false,
    pauseCheckpoint: null,
    pauseReason: null,
    isCancelling: false,
    isCancelled: false,
    templatePreflight: {
        status: "idle",
        templateId: null,
        templateVersion: null,
        questionTypes: [],
        cardCount: null,
        checkedAt: null,
        message: null,
    },
};

// Helper to create inline status messages from events
// These are SHORT human-readable status messages that appear as pills in conversation
// Per backend guidance: LLM content (LLM_OUTPUT, AGENT_CHUNK, thread.message.*) goes to Agent Trace, not pills
const STATUS_EVENT_TYPES = new Set([
    "WORKFLOW_STARTED",   // "Starting task"
    "PROGRESS",           // "Understanding your request", "Created a plan with N steps", "Reasoning step X of Y"
    "AGENT_STARTED",      // "Analyzing the problem", "Taking action"
    "AGENT_COMPLETED",    // "Decided on next step", "Action completed"
    "DELEGATION",         // Multi-agent coordination
    "DATA_PROCESSING",    // "Answer ready"
    "TOOL_INVOKED",       // "Looking this up: '...'"
    "TOOL_OBSERVATION",   // "Fetch: Wantedly Blog...", "Search: Found 5 results..."
    "AGENT_THINKING",     // Short status only (filtered below for long LLM content)
    "APPROVAL_REQUESTED", // Waiting for human approval
    "APPROVAL_DECISION",  // Approval granted/denied
    "WAITING",            // Waiting for dependency or resource
    "DEPENDENCY_SATISFIED", // Dependency is now available
    "STATUS_UPDATE",      // General status update
    "NODE_STARTED",       // Node lifecycle start
    "NODE_COMPLETED",     // Node lifecycle complete
    "NODE_FAILED",        // Node lifecycle failed
]);

// Check if an AGENT_THINKING message is short status vs long LLM content
const isShortStatusMessage = (message: string): boolean => {
    if (!message) return false;
    // Long messages with LLM reasoning content
    if (message.length > 100) return false;
    // Messages starting with "Thinking:" followed by reasoning are LLM content
    if (message.startsWith("Thinking:") && message.length > 50) return false;
    // Messages with markdown formatting are likely LLM content
    if (message.includes("**") || message.includes("REASON:") || message.includes("ACT:")) return false;
    return true;
};

// Events that should clear all status pills (only when workflow ends)
const PROGRESS_CLEARING_EVENTS = new Set([
    "WORKFLOW_COMPLETED",
    "WORKFLOW_FAILED",
]);

const getEventMessage = (event: RunEvent): string | undefined => {
    if ("message" in event && typeof event.message === "string") {
        return event.message;
    }
    return undefined;
};


const getEventMetadata = (event: RunEvent): Record<string, unknown> | undefined => {
    if ("metadata" in event && event.metadata && typeof event.metadata === "object") {
        return event.metadata as Record<string, unknown>;
    }
    return undefined;
};

const coerceContentToString = (value: unknown): string | null => {
    if (typeof value === "string") return value;
    if (!value || typeof value !== "object") return null;
    const record = value as Record<string, unknown>;
    const fallback = record.text ?? record.message ?? record.response ?? record.content ?? record.result;
    if (typeof fallback === "string") return fallback;
    return JSON.stringify(value);
};

const cardsSemanticallyEqual = (a: CardData, b: CardData): boolean => {
    return (
        a.card_id === b.card_id &&
        a.deleted_at === b.deleted_at &&
        a.meta?.modified_at === b.meta?.modified_at &&
        a.edit_state?.status === b.edit_state?.status &&
        a.content?.model === b.content?.model &&
        a.content?.version === b.content?.version &&
        a.content?.data?.front === b.content?.data?.front &&
        a.content?.data?.back === b.content?.data?.back
    );
};

const runSlice = createSlice({
    name: "run",
    initialState,
    reducers: {
        setRunPhase: (state, action: PayloadAction<{ next: RunState["runPhase"]; reason?: string }>) => {
            const { next } = action.payload;
            const allowed: Record<RunState["runPhase"], RunState["runPhase"][]> = {
                idle: ["clearing", "loading", "streaming", "error"],
                clearing: ["loading", "idle", "error"],
                loading: ["hydrated", "streaming", "error"],
                hydrated: ["streaming", "clearing", "idle", "error"],
                streaming: ["hydrated", "error"],
                error: ["clearing", "loading", "idle"],
            };
            if (!state.runPhase || !(state.runPhase in allowed)) {
                state.runPhase = "idle";
            }
            if (state.runPhase === next) return;
            if (!allowed[state.runPhase].includes(next)) {
                debugRun("[RunPhase] Invalid transition:", state.runPhase, "->", next);
                return;
            }
            state.runPhase = next;
        },
        addEvent: (state, action: PayloadAction<HistoricalEvent>) => {
            const rawEvent = action.payload as HistoricalEvent & { task_id?: string };
            const normalizedWorkflowId =
                rawEvent.workflow_id ||
                rawEvent.task_id ||
                (typeof rawEvent.payload === "object" && rawEvent.payload !== null
                    ? String((rawEvent.payload as Record<string, unknown>).workflow_id || (rawEvent.payload as Record<string, unknown>).task_id || "")
                    : "");
            const event: HistoricalEvent = normalizedWorkflowId && !rawEvent.workflow_id
                ? { ...rawEvent, workflow_id: normalizedWorkflowId }
                : rawEvent;
            const isHistorical = event.isHistorical === true;

            // Run detail is task-scoped: live events must belong to the active workflow.
            // Non-matching live events are ignored to prevent task binding drift.
            if (!isHistorical && state.mainWorkflowId) {
                const incomingWorkflowId = (event.workflow_id || "").trim();
                if (!incomingWorkflowId || incomingWorkflowId !== state.mainWorkflowId) {
                    return;
                }
            }

            // Hard idempotency guard: timeline/session reload and SSE reconnect can
            // replay the same event. `workflow_id + stream_id` is the canonical key.
            if (event.stream_id) {
                const duplicatedByStreamID = state.events.some((e) =>
                    e.workflow_id === event.workflow_id && e.stream_id === event.stream_id
                );
                if (duplicatedByStreamID) {
                    return;
                }
            }

            // Deduplicate control events in the events array (for timeline display)
            // But still process state changes for all control events
            const controlEventTypes = ["workflow.pausing", "workflow.paused", "workflow.resumed", "workflow.cancelling", "workflow.cancelled"];
            const isControlEvent = controlEventTypes.includes(event.type);
            let skipEventPush = false;

            if (isControlEvent) {
                const isDuplicate = state.events.some((e: RunEvent) =>
                    e.type === event.type &&
                    e.workflow_id === event.workflow_id
                );
                if (isDuplicate) {
                    debugRun("[Redux] Duplicate control event (will still process state):", event.type);
                    skipEventPush = true; // Don't add to timeline, but continue processing
                }
            }

            if (!skipEventPush) {
                if (event.type === "NODE_STARTED" || event.type === "NODE_COMPLETED" || event.type === "NODE_FAILED") {
                    const payload = "payload" in event ? (event as { payload?: unknown }).payload : undefined;
                    const nodeName = payload && typeof payload === "object"
                        ? String((payload as Record<string, unknown>).node_name || (payload as Record<string, unknown>).event_name || "")
                        : "";
                    if (nodeName) {
                        const existingIndex = state.events.findIndex((e) => {
                            if (e.type !== event.type || e.workflow_id !== event.workflow_id) return false;
                            const existingPayload = "payload" in e ? (e as { payload?: unknown }).payload : undefined;
                            if (!existingPayload || typeof existingPayload !== "object") return false;
                            const existingNode = String(
                                (existingPayload as Record<string, unknown>).node_name ||
                                (existingPayload as Record<string, unknown>).event_name ||
                                ""
                            );
                            return existingNode === nodeName;
                        });
                        if (existingIndex >= 0) {
                            state.events[existingIndex] = event;
                            skipEventPush = true;
                        }
                    }
                }
            }

            if (!skipEventPush) {
                state.events.push(event);
                if (state.events.length > 800) {
                    state.events.splice(0, state.events.length - 800);
                }
            }

            debugRun("[Redux] Received event:", event.type, event);

            // Helper to add/update status message in conversation
            const addStatusMessage = (message: string, eventType: string) => {
                if (!message) return;

                // Always remove existing status message first (we'll re-add at bottom)
                state.messages = state.messages.filter((m) =>
                    !(m.role === "status" && m.taskId === event.workflow_id)
                );

                const statusMsg = {
                    id: `status-${event.workflow_id}`,
                    role: "status" as const,
                    content: message,
                    eventType: eventType,
                    timestamp: new Date().toLocaleTimeString(),
                    taskId: event.workflow_id,
                };

                // Always add at the very end of messages
                state.messages.push(statusMsg);
            };

            // Remove status message when real content arrives
            const clearStatusMessage = () => {
                state.messages = state.messages.filter((m) =>
                    !(m.role === "status" && m.taskId === event.workflow_id)
                );
            };

            // Clear status when actual content events arrive
            if (PROGRESS_CLEARING_EVENTS.has(event.type)) {
                clearStatusMessage();
            }

            // Add inline status messages for informative events
            // Skip for historical events (loaded from API on page reload) - status pills are only for live streaming
            if (STATUS_EVENT_TYPES.has(event.type) && !isHistorical && event.workflow_id) {
                let msg = getEventMessage(event)?.trim();
                const isNodeLifecycle = event.type === "NODE_STARTED" || event.type === "NODE_COMPLETED" || event.type === "NODE_FAILED";
                if ((!msg || msg.length === 0) && isNodeLifecycle && "payload" in event) {
                    const payload = (event as { payload?: unknown }).payload;
                    if (payload && typeof payload === "object") {
                        const record = payload as Record<string, unknown>;
                        const nodeOutput = record.node_output;
                        const nestedMessage =
                            (nodeOutput && typeof nodeOutput === "object" && (
                                (nodeOutput as Record<string, unknown>).progress_message ||
                                (nodeOutput as Record<string, unknown>).status_message ||
                                (nodeOutput as Record<string, unknown>).message
                            )) ||
                            record.message;
                        if (typeof nestedMessage === "string" && nestedMessage.trim()) {
                            msg = nestedMessage.trim();
                        } else {
                            const nodeName = String(record.node_name || record.event_name || "").trim();
                            if (nodeName) {
                                if (event.type === "NODE_STARTED") {
                                    msg = `${nodeName} started`;
                                } else if (event.type === "NODE_COMPLETED") {
                                    msg = `${nodeName} completed`;
                                } else {
                                    msg = `${nodeName} failed`;
                                }
                            }
                        }
                    }
                }
                if (msg && msg.length > 0) {
                    // Skip "All done" since WORKFLOW_COMPLETED handles completion
                    if (event.type === "WORKFLOW_COMPLETED" || msg === "All done") {
                        // Don't add status for completion
                    }
                    // For AGENT_THINKING, only show short status messages (not LLM reasoning content)
                    else if (event.type === "AGENT_THINKING" && !isShortStatusMessage(msg)) {
                        debugRun("[Redux] Skipping long AGENT_THINKING (LLM content):", msg.substring(0, 50));
                    }
                    // Skip any message that's too long for a status pill (max 150 chars)
                    else if (msg.length > 150) {
                        // Node lifecycle events must always advance status; fall back to concise synthesized text.
                        if (isNodeLifecycle && "payload" in event) {
                            const payload = (event as { payload?: unknown }).payload;
                            if (payload && typeof payload === "object") {
                                const record = payload as Record<string, unknown>;
                                const nodeName = String(record.node_name || record.event_name || "").trim();
                                if (nodeName) {
                                    if (event.type === "NODE_STARTED") {
                                        msg = `${nodeName} started`;
                                    } else if (event.type === "NODE_COMPLETED") {
                                        msg = `${nodeName} completed`;
                                    } else {
                                        msg = `${nodeName} failed`;
                                    }
                                    addStatusMessage(msg, event.type);
                                    debugRun("[Redux] Added fallback node lifecycle status:", msg);
                                }
                            }
                        } else {
                            debugRun("[Redux] Skipping long status message:", msg.substring(0, 50) + "...");
                        }
                    }
                    else {
                        addStatusMessage(msg, event.type);
                        debugRun("[Redux] Added status message:", msg);
                    }
                }
            }

            // Update status based on event type
            // Priority: STREAM_END/done > WORKFLOW_COMPLETED (main workflow only)
            if (event.type === "done" || event.type === "STREAM_END") {
                // STREAM_END or done is the authoritative "stream finished" marker
                if (state.status !== "failed") {
                    state.status = "completed";
                }
                debugRun("[Redux] Stream ended (event type:", event.type, ")");

                // Remove generating placeholder and status messages when stream ends
                state.messages = state.messages.filter((m) => !m.isGenerating && m.role !== "status");
                debugRun("[Redux] Removed generating placeholders and status messages on stream end");

                // Check if we have any assistant messages
                const hasAssistantMessage = state.messages.some(m => m.role === "assistant" && !m.isStreaming);
                if (!hasAssistantMessage) {
                    debugRun("[Redux] Stream completion event received but no assistant message found - fetchFinalOutput should trigger");
                }
            } else if (event.type === "WORKFLOW_COMPLETED") {
                // WORKFLOW_COMPLETED is treated as completion for the main workflow
                // Sub-workflows also emit WORKFLOW_COMPLETED but are ignored via workflow_id check
                const isMainWorkflow = event.workflow_id === state.mainWorkflowId;

                // For historical data (mainWorkflowId is null), only accept WORKFLOW_COMPLETED
                // if the message indicates it's the main workflow completion ("All done")
                // This prevents sub-agent completions from incorrectly marking the task as complete
                const workflowMessage = getEventMessage(event);
                const isMainWorkflowMessage = workflowMessage === "All done" ||
                    workflowMessage?.includes("workflow completed");
                const isHistoricalData = state.mainWorkflowId === null &&
                    state.status !== "completed" &&
                    isMainWorkflowMessage;

                if (isMainWorkflow || isHistoricalData) {
                    debugRun(`[Redux] Main workflow completed - marking as completed ${isHistoricalData ? "(historical)" : "(live)"}`,
                        "message:", workflowMessage);
                    // Mark as completed. If STREAM_END arrives later, it will simply confirm completion.
                    // This handles workflows that don't emit STREAM_END (edge cases).
                    state.status = "completed";

                    // Remove all status pills on terminal completion to avoid stale "started" leftovers
                    // caused by inconsistent workflow_id across progress events.
                    state.messages = state.messages.filter((m) => m.role !== "status");
                    // Remove generating placeholder for this workflow if present.
                    state.messages = state.messages.filter((m) =>
                        !(m.isGenerating && m.taskId === event.workflow_id)
                    );
                    debugRun("[Redux] Cleared status messages and removed generating placeholder for completed workflow");
                } else if (state.mainWorkflowId === null) {
                    // Log sub-workflow completion but don't mark as complete
                    debugRun("[Redux] Sub-workflow completed (not main workflow):", event.workflow_id,
                        "message:", workflowMessage);
                }
            } else if (event.type === "WORKFLOW_FAILED") {
                state.status = "failed";
                // Remove generating placeholders and status messages on failure
                state.messages = state.messages.filter((m) => !m.isGenerating && m.role !== "status");
                const failedMessage = getEventMessage(event);
                if (failedMessage) {
                    debugRun("[Redux] Workflow failed:", failedMessage);
                } else {
                    debugRun("[Redux] Workflow failed (no message)");
                }
            } else if (event.type === "workflow.pausing") {
                // Pause request received, workflow will pause at next checkpoint
                // Skip if already paused (control-state already set the correct status)
                if (state.isPaused) {
                    debugRun("[Redux] Skipping workflow.pausing - already paused");
                    return;
                }
                const pausingMessage = getEventMessage(event);
                debugRun("[Redux] Workflow pausing:", pausingMessage);
                addStatusMessage(pausingMessage || "Pausing at next checkpoint...", "workflow.pausing");
            } else if (event.type === "workflow.paused") {
                // Workflow is now paused
                // Skip status update if already paused (control-state already set it)
                const wasAlreadyPaused = state.isPaused;
                state.isPaused = true;
                const pausedEvent = event as WorkflowPausedEvent;
                state.pauseCheckpoint = pausedEvent.checkpoint || null;
                state.pauseReason = getEventMessage(pausedEvent) || null;
                debugRun("[Redux] Workflow paused at checkpoint:", state.pauseCheckpoint);
                // Only update status if we weren't already paused
                if (!wasAlreadyPaused) {
                    addStatusMessage("Workflow paused", "workflow.paused");
                }
            } else if (event.type === "workflow.resumed") {
                // Workflow resumed, clear pause state
                state.isPaused = false;
                state.pauseCheckpoint = null;
                state.pauseReason = null;
                debugRun("[Redux] Workflow resumed:", getEventMessage(event));
                // Clear status message or update to show resumed
                clearStatusMessage();
            } else if (event.type === "workflow.cancelling") {
                // Cancel request received, workflow will cancel
                // Skip if already cancelling (control-state already set it)
                if (state.isCancelling) {
                    debugRun("[Redux] Skipping workflow.cancelling - already cancelling");
                    return;
                }
                state.isCancelling = true;
                const cancellingMessage = getEventMessage(event);
                debugRun("[Redux] Workflow cancelling:", cancellingMessage);
                addStatusMessage(cancellingMessage || "Cancelling...", "workflow.cancelling");
            } else if (event.type === "workflow.cancelled") {
                // Workflow is now cancelled
                state.status = "failed"; // Treat cancelled as a terminal state
                state.isCancelling = false;
                state.isCancelled = true;
                state.isPaused = false;
                state.pauseCheckpoint = null;

                // Find the generating placeholder to get taskId
                const generatingMsg = state.messages.find((m) => m.isGenerating);
                const taskId = generatingMsg?.taskId || event.workflow_id;

                // Remove generating placeholders and old status messages
                state.messages = state.messages.filter((m) => !m.isGenerating && m.role !== "status");

                // Add a proper system message (same style as history loading)
                state.messages.push({
                    id: `system-cancelled-${Date.now()}`,
                    role: "system" as const,
                    content: "This task was cancelled before it could complete.",
                    timestamp: new Date().toLocaleTimeString(),
                    taskId: taskId,
                    isCancelled: true,
                });
                debugRun("[Redux] Workflow cancelled:", getEventMessage(event));
            } else if (event.type === "error") {
                state.status = "failed";
                // Remove generating placeholders and status messages on error
                state.messages = state.messages.filter((m) => !m.isGenerating && m.role !== "status");
                debugRun("[Redux] Removed generating placeholders and status messages on error");
            } else if (state.status === "idle" && event.workflow_id) {
                state.status = "running";
            }

            // Note: We intentionally do NOT auto-update selectedAgent from WORKFLOW_STARTED events.
            // The user's agent selection (via dropdown) is authoritative. Session loading already
            // restores historical agent selection when loading a session. Auto-updating here would
            // override the user's explicit choice when they switch modes for follow-up messages.

            // Add timeline metadata for better display
            if (event.type === "WORKFLOW_STARTED" ||
                event.type === "AGENT_STARTED" ||
                event.type === "AGENT_THINKING" ||
                event.type === "LLM_PROMPT" ||
                event.type === "DATA_PROCESSING" ||
                event.type === "PROGRESS" ||
                event.type === "DELEGATION") {
                // These are already in events array, just need to ensure they have display data
                // The timeline component will read from events array
            }

            // Helper to identify intermediate sub-agent outputs that should only appear in timeline/agent trace
            // Per backend guidance: Don't show synthesis messages during streaming - wait for WORKFLOW_COMPLETED
            // The authoritative final answer is fetched via API after completion (fetchFinalOutput)
            const isIntermediateSubAgent = (agentId: string | undefined): boolean => {
                // Empty agent_id is treated as final output (simple responses from non-research tasks)
                if (!agentId) return false;

                // Title generator is handled separately (not shown in conversation)
                if (agentId === "title_generator") return true;

                // WHITELIST: Only simple-agent shows directly (for non-research simple tasks)
                // synthesis outputs are intermediate during streaming - final answer comes from API fetch
                const directOutputAgents = [
                    "simple-agent",        // Simple task agent (non-research)
                ];

                // If it's a direct output agent, don't skip it
                if (directOutputAgents.includes(agentId)) return false;

                // Everything else is intermediate including synthesis (final answer via fetchFinalOutput)
                return true;
            };

            // Skip title generation deltas (they're not messages)
            if (event.type === "thread.message.delta" && event.agent_id === "title_generator") {
                return;
            }

            // Skip intermediate sub-agent outputs (timeline only, not conversation)
            // Exception: title_generator completed events need to pass through to set sessionTitle
            if ((event.type === "thread.message.delta" || event.type === "thread.message.completed" || event.type === "LLM_OUTPUT")
                && isIntermediateSubAgent(event.agent_id)
                && !(event.type === "thread.message.completed" && event.agent_id === "title_generator")) {
                debugRun("[Redux] Skipping intermediate sub-agent message (timeline only):", event.agent_id);
                return;
            }

            // Handle streaming message deltas (agent trace messages)
            if (event.type === "thread.message.delta") {
                // Accumulate streaming text deltas
                const deltaEvent: ThreadMessageDeltaEvent = event;

                // Filter out deltas that are diagnostic/system messages (should only appear in timeline)
                const deltaContent = typeof deltaEvent.delta === "string" ? deltaEvent.delta : "";
                if (deltaContent) {
                    if (deltaContent.startsWith('[Incomplete response:') || deltaContent.includes('Task budget at')) {
                        debugRun("[Redux] Skipping delta with diagnostic/system message (timeline only)");
                        return;
                    }
                }

                // Find the last streaming assistant message (NOT the generating placeholder - keep that visible)
                // We search from the end because it should be recent
                let streamingMsgIndex = -1;

                for (let i = state.messages.length - 1; i >= 0; i--) {
                    if (state.messages[i].role === "assistant" && state.messages[i].isStreaming && state.messages[i].taskId === event.workflow_id) {
                        streamingMsgIndex = i;
                        break;
                    }
                }

                debugRun("[Redux] Delta received:", deltaContent, "Streaming msg index:", streamingMsgIndex);

                if (streamingMsgIndex !== -1) {
                    // Append delta to existing streaming message
                    state.messages[streamingMsgIndex].content += deltaContent;
                    state.messages[streamingMsgIndex].taskId = state.messages[streamingMsgIndex].taskId || event.workflow_id;

                    // Update metadata if provided in delta (e.g. citations)
                    if (deltaEvent.metadata) {
                        state.messages[streamingMsgIndex].metadata = {
                            ...state.messages[streamingMsgIndex].metadata,
                            ...deltaEvent.metadata
                        };
                    }
                    debugRun("[Redux] Appended to existing message");
                } else {
                    // Create new streaming message with unique ID
                    // Insert it BEFORE the generating placeholder if one exists
                    const uniqueId = `${event.agent_id || 'assistant'}-${event.workflow_id}-${Date.now()}`;
                    const newMessage = {
                        id: uniqueId,
                        role: "assistant" as const,
                        sender: event.agent_id, // Set sender for agent trace filtering
                        content: deltaEvent.delta || "",
                        timestamp: new Date().toLocaleTimeString(),
                        isStreaming: true,
                        taskId: event.workflow_id,
                        metadata: deltaEvent.metadata, // Store metadata if provided
                    };

                    // Find generating placeholder to insert before it
                    const generatingIndex = state.messages.findIndex((m) =>
                        m.role === "assistant" && m.isGenerating && m.taskId === event.workflow_id
                    );

                    if (generatingIndex !== -1) {
                        // Insert before generating placeholder
                        state.messages.splice(generatingIndex, 0, newMessage);
                        debugRun("[Redux] Created new streaming message before generating placeholder");
                    } else {
                        // No placeholder, append normally
                        state.messages.push(newMessage);
                        debugRun("[Redux] Created new streaming message");
                    }
                }
            } else if (event.type === "thread.message.completed") {
                const completedEvent: ThreadMessageCompletedEvent = event;

                // Handle title generation messages - just store the title (first-title-wins)
                if (event.agent_id === "title_generator") {
                    const title = completedEvent.response || coerceContentToString(completedEvent.content);
                    if (title && !state.sessionTitle) {
                        // Only set title once (first message wins, aligned with backend)
                        state.sessionTitle = title;
                        debugRun("[Redux] Session title set:", title);
                    } else if (title && state.sessionTitle) {
                        debugRun("[Redux] Session title already set, ignoring:", title);
                    }
                    return;
                }

                // For non-title messages: handle completions (agent trace messages)
                // Find the last streaming assistant message (NOT the generating placeholder - keep that visible)
                let streamingMsgIndex = -1;

                for (let i = state.messages.length - 1; i >= 0; i--) {
                    if (state.messages[i].role === "assistant" && state.messages[i].isStreaming && state.messages[i].taskId === event.workflow_id) {
                        streamingMsgIndex = i;
                        break;
                    }
                }

                debugRun("[Redux] thread.message.completed event:", completedEvent);
                debugRun("[Redux] Message completed, response:", completedEvent.response?.substring(0, 100));
                const completedMetadata = getEventMetadata(completedEvent);
                debugRun("[Redux] Metadata:", completedMetadata);
                if (completedMetadata) {
                    const citations = (completedMetadata as { citations?: unknown }).citations;
                    if (Array.isArray(citations)) {
                        debugRun("[Redux] Citations found:", citations.length);
                    }
                }

                if (streamingMsgIndex !== -1) {
                    // Check if this is a diagnostic/system message before updating (should only appear in timeline)
                    const responseContent = completedEvent.response || "";
                    if (responseContent && typeof responseContent === 'string') {
                        if (responseContent.startsWith('[Incomplete response:') || responseContent.includes('Task budget at')) {
                            debugRun("[Redux] Removing streaming message with diagnostic/system content (timeline only)");
                            // Remove the streaming message instead of updating it with the error
                            state.messages.splice(streamingMsgIndex, 1);
                            return;
                        }
                    }

                    // Update existing streaming message
                    const msg = state.messages[streamingMsgIndex];
                    msg.isStreaming = false;
                    msg.taskId = msg.taskId || event.workflow_id;
                    // If response is provided, use it (it's the complete text); otherwise keep accumulated content
                    if (completedEvent.response) {
                        msg.content = completedEvent.response;
                        debugRun("[Redux] Updated streaming message with complete response");
                    }
                    msg.metadata = completedMetadata;
                } else {
                    // No streaming occurred, create new message with response before generating placeholder
                    const content = completedEvent.response || coerceContentToString(completedEvent.content) || "";

                    // Filter out diagnostic/system/status messages that should only appear in timeline
                    if (content && typeof content === 'string') {
                        const lowerContent = content.toLowerCase();
                        if (content.startsWith('[Incomplete response:') ||
                            content.includes('Task budget at') ||
                            lowerContent.includes('task completed') ||
                            lowerContent.includes('task done') ||
                            lowerContent === 'done' ||
                            lowerContent === 'completed' ||
                            lowerContent === 'success' ||
                            (lowerContent.includes('successfully') && content.length < 100)) {
                            debugRun("[Redux] Skipping status/system message in thread.message.completed (timeline only):", content);
                            return;
                        }
                    }

                    if (content) {
                        // Per backend guidance: synthesis outputs during streaming are intermediate
                        // The final answer is fetched via API after WORKFLOW_COMPLETED
                        const isSynthesisAgent = ["synthesis", "streaming_synthesis"].includes(event.agent_id || "");

                        if (isSynthesisAgent) {
                            debugRun("[Redux] Skipping synthesis thread.message.completed - final answer will come from API fetch");
                            return;
                        }

                        const uniqueId = `${event.agent_id || 'assistant'}-${event.workflow_id}-${event.seq || Date.now()}`;

                        // For simple-agent, remove generating placeholder
                        if (event.agent_id === "simple-agent") {
                            debugRun("[Redux] 🎯 Simple-agent from thread.message.completed");
                            state.messages = state.messages.filter((m) =>
                                !(m.isGenerating && m.taskId === event.workflow_id)
                            );
                        }

                        const newMessage = {
                            id: uniqueId,
                            role: "assistant" as const,
                            sender: completedEvent.agent_id,
                            content: content,
                            timestamp: new Date().toLocaleTimeString(),
                            metadata: completedMetadata,
                            taskId: event.workflow_id,
                        };

                        // Find generating placeholder to insert before it (if not already removed)
                        const generatingIndex = state.messages.findIndex((m) =>
                            m.role === "assistant" && m.isGenerating && m.taskId === event.workflow_id
                        );

                        if (generatingIndex !== -1) {
                            // Insert before generating placeholder
                            state.messages.splice(generatingIndex, 0, newMessage);
                            debugRun("[Redux] Created new message from completion event before generating placeholder");
                        } else {
                            // No placeholder, append normally
                            state.messages.push(newMessage);
                            debugRun("[Redux] Created new message from completion event");
                        }
                    } else {
                        debugRun("[Redux] thread.message.completed has no content! Event:", completedEvent);
                    }
                }
            } else if (event.type === "LLM_OUTPUT") {
                // Handle LLM_OUTPUT event (sometimes used instead of thread.message.*)
                const llmEvent: LlmOutputEvent = event;
                debugRun("[Redux] LLM_OUTPUT event:", llmEvent);

                const payloadText = llmEvent.payload?.text;
                const content = typeof payloadText === "string" ? payloadText : (llmEvent.message || "");
                debugRun("[Redux] LLM_OUTPUT content:", content?.substring(0, 100));

                // Filter out diagnostic/system messages that should only appear in timeline
                // These are system notifications from the backend
                if (content && typeof content === 'string') {
                    if (content.startsWith('[Incomplete response:') || content.includes('Task budget at')) {
                        debugRun("[Redux] Skipping diagnostic/system message (timeline only)");
                        return;
                    }
                }

                // Per backend guidance: synthesis outputs during streaming are intermediate
                // The final answer is fetched via API after WORKFLOW_COMPLETED
                // Only show simple-agent outputs directly (non-research tasks)
                const isSynthesisAgent = ["synthesis", "streaming_synthesis"].includes(event.agent_id || "");

                if (isSynthesisAgent) {
                    debugRun("[Redux] Skipping synthesis LLM_OUTPUT - final answer will come from API fetch");
                    return;
                }

                if (content) {
                    const uniqueId = `${event.agent_id || 'assistant'}-${event.workflow_id}-${event.seq || Date.now()}`;

                    // For simple-agent, remove generating placeholder
                    if (event.agent_id === "simple-agent") {
                        debugRun("[Redux] 🎯 Simple-agent output received");
                        state.messages = state.messages.filter((m) =>
                            !(m.isGenerating && m.taskId === event.workflow_id)
                        );
                    }

                    state.messages.push({
                        id: uniqueId,
                        role: "assistant",
                        sender: event.agent_id,
                        content: content,
                        timestamp: new Date().toLocaleTimeString(),
                        metadata: getEventMetadata(event),
                        taskId: event.workflow_id,
                    });
                    debugRun("[Redux] Created new message from LLM_OUTPUT, total messages:", state.messages.length);
                } else {
                    debugRun("[Redux] LLM_OUTPUT event has no content");
                }
            } else if (event.type === "WORKFLOW_COMPLETED") {
                // Historical timeline replay should not synthesize conversation messages.
                // Session conversation API is the single source of truth for past assistant output.
                if (isHistorical) {
                    return;
                }
                // Workflow completed - check if there's a final result to show
                debugRun("[Redux] WORKFLOW_COMPLETED event:", event);

                // Check if we already have an assistant message
                const hasAssistantMessage = state.messages.some(m => m.role === "assistant");
                debugRun("[Redux] Has assistant message:", hasAssistantMessage);
                debugRun("[Redux] Current messages:", state.messages.length);
                const workflowMessage = getEventMessage(event);
                debugRun("[Redux] Workflow event message:", workflowMessage);

                // If no assistant message and the event has a message/result, add it
                // Note: WORKFLOW_COMPLETED usually just has "All done", not the actual result
                // We should ONLY add substantive content, not status messages
                if (!hasAssistantMessage && workflowMessage && workflowMessage !== "All done") {
                    // Filter out diagnostic/system/status messages that shouldn't appear as conversation content
                    const message = workflowMessage;
                    if (message && typeof message === 'string') {
                        const lowerMessage = message.toLowerCase();
                        // Skip status-like messages (these should only appear in timeline, not conversation)
                        if (message.startsWith('[Incomplete response:') ||
                            message.includes('Task budget at') ||
                            lowerMessage.includes('task completed') ||
                            lowerMessage.includes('task done') ||
                            lowerMessage === 'done' ||
                            lowerMessage === 'completed' ||
                            lowerMessage === 'success' ||
                            lowerMessage.includes('successfully') && message.length < 100) { // Short success messages are status, not content
                            debugRun("[Redux] Skipping status/system message in WORKFLOW_COMPLETED (timeline only):", message);
                            return;
                        }
                    }

                    const uniqueId = `workflow-${event.workflow_id}-${Date.now()}`;
                    state.messages.push({
                        id: uniqueId,
                        role: "assistant",
                        content: workflowMessage,
                        timestamp: new Date().toLocaleTimeString(),
                        taskId: event.workflow_id,
                    });
                    debugRun("[Redux] Added final result from WORKFLOW_COMPLETED");
                } else {
                    debugRun("[Redux] Not adding message from WORKFLOW_COMPLETED - will rely on fallback fetch");
                }
            } else if (event.type === "AGENT_COMPLETED") {
                // AGENT_COMPLETED is just a status event, not a message
                // The actual response comes from thread.message.completed
                // Don't add this to messages - it's just "Task done" status
                debugRun("[Redux] Agent completed, skipping message creation");
            } else if (event.type === "TOOL_INVOKED") {
                // Tool invocations are only shown in the timeline (via state.events), not in the conversation
                debugRun("[Redux] Tool invoked, skipping message creation (timeline only)");
            } else if (event.type === "TOOL_OBSERVATION") {
                // Tool observations are only shown in the timeline (via state.events), not in the conversation
                debugRun("[Redux] Tool observation, skipping message creation (timeline only)");
            }
        },
        resetRun: (state) => {
            state.events = [];
            state.messages = [];
            state.status = "idle";
            state.connectionState = "idle";
            state.streamError = null;
            state.sessionTitle = null;
            state.mainWorkflowId = null;
            // Reset pause/resume/cancel state
            state.isPaused = false;
            state.pauseCheckpoint = null;
            state.pauseReason = null;
            state.isCancelling = false;
            state.isCancelled = false;
            state.templatePreflight = {
                status: "idle",
                templateId: null,
                templateVersion: null,
                questionTypes: [],
                cardCount: null,
                checkedAt: null,
                message: null,
            };
            state.cards = [];
            state.cardsVersion += 1;
            state.runPhase = "idle";
            // Keep selectedAgent persistent across sessions - it's a user preference/mode
        },
        upsertCard: (state, action: PayloadAction<CardData>) => {
            if (!state.cards) state.cards = [];
            const index = state.cards.findIndex(card => card.card_id === action.payload.card_id);
            if (index !== -1) {
                if (cardsSemanticallyEqual(state.cards[index], action.payload)) {
                    return;
                }
                state.cards[index] = action.payload;
            } else {
                state.cards.push(action.payload);
            }
            state.cardsVersion += 1;
        },
        upsertCardsBatch: (state, action: PayloadAction<CardData[]>) => {
            if (!state.cards) state.cards = [];
            const incoming = action.payload || [];
            if (!incoming.length) return;

            let changed = false;
            for (const nextCard of incoming) {
                if (!nextCard?.card_id) continue;
                const index = state.cards.findIndex((card) => card.card_id === nextCard.card_id);
                if (index !== -1) {
                    if (!cardsSemanticallyEqual(state.cards[index], nextCard)) {
                        state.cards[index] = nextCard;
                        changed = true;
                    }
                } else {
                    state.cards.push(nextCard);
                    changed = true;
                }
            }

            if (changed) {
                state.cardsVersion += 1;
            }
        },
        setCards: (state, action: PayloadAction<CardData[]>) => {
            const nextCards = action.payload || [];
            if (state.cards.length === nextCards.length) {
                let changed = false;
                for (let i = 0; i < nextCards.length; i += 1) {
                    const current = state.cards[i];
                    const next = nextCards[i];
                    if (!current || !next || !cardsSemanticallyEqual(current, next)) {
                        changed = true;
                        break;
                    }
                }
                if (!changed) {
                    return;
                }
            }
            state.cards = action.payload;
            state.cardsVersion += 1;
        },
        removeCard: (state, action: PayloadAction<string>) => {
            if (!state.cards) state.cards = [];
            state.cards = state.cards.filter(c => c.card_id !== action.payload);
            state.cardsVersion += 1;
        },
        updateCardStatus: (state, action: PayloadAction<{ card_id: string; status: CardData["edit_state"]["status"] }>) => {
            const index = state.cards.findIndex(card => card.card_id === action.payload.card_id);
            if (index !== -1) {
                state.cards[index] = {
                    ...state.cards[index],
                    edit_state: {
                        ...state.cards[index].edit_state,
                        status: action.payload.status,
                    },
                };
                state.cardsVersion += 1;
            }
        },
        updateCardQuestionType: (state, action: PayloadAction<{ card_id: string; questionType: CardData["content"]["model"] }>) => {
            const index = state.cards.findIndex(card => card.card_id === action.payload.card_id);
            if (index !== -1) {
                state.cards[index] = {
                    ...state.cards[index],
                    content: {
                        ...state.cards[index].content,
                        model: action.payload.questionType,
                    },
                };
                state.cardsVersion += 1;
            }
        },
        bulkUpdateStatus: (state, action: PayloadAction<{ card_ids: string[]; status: CardData["edit_state"]["status"] }>) => {
            const idSet = new Set(action.payload.card_ids);
            state.cards = state.cards.map(card => (
                idSet.has(card.card_id)
                    ? { ...card, edit_state: { ...card.edit_state, status: action.payload.status } }
                    : card
            ));
            state.cardsVersion += 1;
        },
        bulkUpdateQuestionType: (state, action: PayloadAction<{ card_ids: string[]; questionType: CardData["content"]["model"] }>) => {
            const idSet = new Set(action.payload.card_ids);
            state.cards = state.cards.map(card => (
                idSet.has(card.card_id)
                    ? { ...card, content: { ...card.content, model: action.payload.questionType } }
                    : card
            ));
            state.cardsVersion += 1;
        },
        addMessage: (state, action: PayloadAction<RunMessage>) => {
            const normalizedMessage = normalizeMessageForStore(action.payload);
            debugRun("[Redux] addMessage called:", normalizedMessage);
            if (!state.messages.some(m => m.id === normalizedMessage.id)) {
                state.messages.push(normalizedMessage);
                debugRun("[Redux] Message added to state");
            } else {
                debugRun("[Redux] Message with ID already exists:", normalizedMessage.id);
            }
        },
        updateMessageMetadata: (state, action: PayloadAction<{ taskId: string; metadata: Record<string, unknown> }>) => {
            const { taskId, metadata } = action.payload;
            debugRun("[Redux] updateMessageMetadata called for task:", taskId);

            // Find the last assistant message for this task
            for (let i = state.messages.length - 1; i >= 0; i--) {
                const msg = state.messages[i];
                if (msg.role === "assistant" && msg.taskId === taskId) {
                    debugRun("[Redux] Updating metadata for message:", msg.id, "Citations:", metadata?.citations?.length);
                    // Create a new object to trigger React re-render
                    state.messages[i] = {
                        ...msg,
                        metadata: { ...msg.metadata, ...metadata }
                    };
                    break;
                }
            }
        },
        setConnectionState: (state, action: PayloadAction<RunState["connectionState"]>) => {
            state.connectionState = action.payload;
            if (action.payload === "connected") {
                state.streamError = null;
            }
        },
        setStreamError: (state, action: PayloadAction<string | null>) => {
            state.streamError = action.payload;
            if (action.payload) {
                state.connectionState = "error";
            }
        },
        setSelectedAgent: (state, action: PayloadAction<RunState["selectedAgent"]>) => {
            state.selectedAgent = action.payload;
        },
        setResearchStrategy: (state, action: PayloadAction<RunState["researchStrategy"]>) => {
            state.researchStrategy = action.payload;
        },
        setMainWorkflowId: (state, action: PayloadAction<string | null>) => {
            state.mainWorkflowId = action.payload;
            debugRun("[Redux] Main workflow ID set to:", action.payload);
        },
        setStatus: (state, action: PayloadAction<RunState["status"]>) => {
            state.status = action.payload;
            debugRun("[Redux] Status manually set to:", action.payload);
        },
        setPaused: (state, action: PayloadAction<{ paused: boolean; checkpoint?: string; reason?: string }>) => {
            state.isPaused = action.payload.paused;
            state.pauseCheckpoint = action.payload.checkpoint || null;
            state.pauseReason = action.payload.reason || null;

            // Update status message to match pause state
            if (action.payload.paused) {
                // Remove old status and add paused status
                state.messages = state.messages.filter((m) => m.role !== "status");
                state.messages.push({
                    id: `status-paused-${Date.now()}`,
                    role: "status" as const,
                    content: "Workflow paused",
                    eventType: "workflow.paused",
                    timestamp: new Date().toLocaleTimeString(),
                });
            } else {
                // Resumed - clear status message
                state.messages = state.messages.filter((m) => m.role !== "status");
            }
            debugRun("[Redux] Pause state set:", action.payload);
        },
        setCancelling: (state, action: PayloadAction<boolean | { value: boolean; message?: string }>) => {
            const payload = typeof action.payload === "boolean"
                ? { value: action.payload, message: undefined }
                : action.payload;
            state.isCancelling = payload.value;

            // Update status message to match cancelling state
            if (payload.value) {
                // Remove old status and add cancelling status
                state.messages = state.messages.filter((m) => m.role !== "status");
                state.messages.push({
                    id: `status-cancelling-${Date.now()}`,
                    role: "status" as const,
                    content: payload.message || "Cancelling workflow…",
                    eventType: "workflow.cancelling",
                    timestamp: new Date().toLocaleTimeString(),
                });
            } else {
                // Cancelled complete - clear status message
                state.messages = state.messages.filter((m) => m.role !== "status");
            }
            debugRun("[Redux] Cancelling state set to:", action.payload);
        },
        setCancelled: (state, action: PayloadAction<boolean | { value: boolean; message?: string }>) => {
            const payload = typeof action.payload === "boolean"
                ? { value: action.payload, message: undefined }
                : action.payload;
            state.isCancelled = payload.value;
            state.isCancelling = false;

            if (payload.value) {
                // Task is cancelled - update status and replace generating placeholder with cancelled message
                state.status = "failed";

                // Find and remove the generating placeholder, capturing its taskId for the replacement message
                const generatingMsg = state.messages.find((m) => m.isGenerating);
                const taskId = generatingMsg?.taskId;

                // Remove generating placeholders and status messages
                state.messages = state.messages.filter((m) => !m.isGenerating && m.role !== "status");

                // Add a proper system message (same style as history loading) instead of status pill
                state.messages.push({
                    id: `system-cancelled-${Date.now()}`,
                    role: "system" as const,
                    content: payload.message || "This task was cancelled before it could complete.",
                    timestamp: new Date().toLocaleTimeString(),
                    taskId: taskId,
                    isCancelled: true,
                });
            }
            debugRun("[Redux] Cancelled state set to:", action.payload);
        },
        setTemplatePreflight: (state, action: PayloadAction<RunState["templatePreflight"]>) => {
            state.templatePreflight = action.payload;
        },
        clearTemplatePreflight: (state) => {
            state.templatePreflight = {
                status: "idle",
                templateId: null,
                templateVersion: null,
                questionTypes: [],
                cardCount: null,
                checkedAt: null,
                message: null,
            };
        },
    },
});

export const {
    addEvent, resetRun, addMessage, updateMessageMetadata,
    setConnectionState, setStreamError, setSelectedAgent,
    setResearchStrategy, setMainWorkflowId, setStatus,
    setPaused, setCancelling, setCancelled, setRunPhase, setTemplatePreflight, clearTemplatePreflight,
    upsertCard, upsertCardsBatch, setCards, removeCard,
    updateCardStatus, updateCardQuestionType, bulkUpdateStatus, bulkUpdateQuestionType
} = runSlice.actions;
export default runSlice.reducer;

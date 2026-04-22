"use client";

import { useRunStream } from "@/lib/kardcraft/stream";
import { getTask, isUnauthenticatedApiError, toUiErrorMessage } from "@/lib/kardcraft/api";
import {
    getSession,
    getSessionConversation,
    getSessionHistory,
    getSessionState,
    getSessionTimeline,
    getSessionWorkspace,
} from "@/lib/kardcraft/session-repository";
import { RunEvent } from "@/lib/kardcraft/types";
import { useRunCommands, useRunSelector, useRunSession } from "@/lib/run/system";
import { projectDomainEventToRunEvent, RunDomainEvent } from "@/lib/run/domain-events";
import { createSessionBundleLoaderMachine } from "@/lib/run/session-bundle-loader-machine";
import { createWorkspaceLoaderMachine, inferWorkspacePhaseFromData } from "@/lib/run/workspace-loader-machine";
import { CardData, createDraftSessionId, RunMessage } from "@/lib/run/types";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from "react";
import { SessionDataBundle, SessionHistoryData } from "../run-detail-types";
import { useScrollSync } from "./use-scroll-sync";
import { useTaskControls } from "./use-task-controls";
import { TimelineDisplayEvent, useTimeline } from "./use-timeline";
import { createActor } from "xstate";
import { useSelector as useActorSelector } from "@xstate/react";

export interface RunDetailState {
    sessionId: string | null;
    workflowIdParam: string | null;
    isNewSession: boolean;
    actualSessionId: string | null;
    resolvedSessionId: string | null;
    isLoading: boolean;
    error: string | null;
    messages: RunMessage[];
    runEvents: RunEvent[];
    runStatus: "idle" | "running" | "completed" | "failed";
    runPhase: "idle" | "clearing" | "loading" | "hydrated" | "streaming" | "error";
    connectionState: "idle" | "connecting" | "connected" | "reconnecting" | "error";
    streamError: string | null;
    sessionTitle: string | null;
    selectedAgent: "normal" | "card_template";
    researchStrategy: "quick" | "standard" | "deep" | "academic";
    isPaused: boolean;
    pauseCheckpoint: string | null;
    isPauseLoading: boolean;
    isResumeLoading: boolean;
    canControlTask: boolean;
    isCancelling: boolean;
    isCancelled: boolean;
    cards: CardData[];
    sessionData: SessionDataBundle | null;
    sessionHistory: SessionHistoryData;
    currentTaskId: string | null;
    workspacePhase: "idle" | "clearing" | "loading" | "hydrated" | "empty" | "error";
    loadPhase: "idle" | "clearing" | "loading" | "hydrated" | "streaming";
    activeTab: string;
    setActiveTab: (value: string) => void;
    isTimelineOpen: boolean;
    setIsTimelineOpen: (open: boolean) => void;
    showWorkspace: boolean;
    setShowWorkspace: (show: boolean) => void;
    workspaceExpanded: boolean;
    setWorkspaceExpanded: (expanded: boolean) => void;
    timelineEvents: TimelineDisplayEvent[];
    conversationScrollRef: React.RefObject<HTMLDivElement>;
    timelineScrollRef: React.RefObject<HTMLDivElement>;
    handleRetryStream: () => void;
    handleFetchFinalOutputClick: () => void;
    handleTaskCreated: (newTaskId: string, query: string, workflowId?: string, newSessionId?: string, attachments?: Array<{fileId: string; filename: string; size: number; mimeType: string}>) => void;
    handlePause: () => void;
    handleResume: () => void;
    handleCancel: () => void;
    scrollToMessage: (messageId: string) => void;
    setSelectedAgentValue: (agent: "normal" | "card_template") => void;
    setResearchStrategyValue: (strategy: "quick" | "standard" | "deep" | "academic") => void;
    isPending: boolean;
    startTransition: (cb: () => void) => void;
}

const formatMessageTimestamp = (raw?: string): string => {
    if (!raw) return new Date().toLocaleTimeString();
    const parsed = Date.parse(raw);
    if (!Number.isNaN(parsed)) {
        return new Date(parsed).toLocaleTimeString();
    }
    return raw;
};

const normalizeMessageAttachments = (
    attachments: Array<{ file_id: string; filename: string; size: number; mime_type: string }> | undefined,
) => {
    if (!Array.isArray(attachments)) return undefined;
    return attachments.map((item) => ({
        fileId: item.file_id,
        filename: item.filename,
        size: item.size,
        mimeType: item.mime_type,
    }));
};

const normalizeWorkflowId = (value: string | null | undefined): string | null => {
    if (typeof value !== "string") return null;
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
};

const toRunDetailErrorMessage = (err: unknown, fallback: string): string =>
    toUiErrorMessage(err, fallback);

const mapHistoryTaskStatus = (value: string | undefined): "idle" | "running" | "completed" | "failed" | null => {
    if (!value) return null;
    const normalized = value.trim().toLowerCase().replace(/^task_status_/, "");
    if (normalized === "running" || normalized === "queued") return "running";
    if (normalized === "completed") return "completed";
    if (normalized === "failed" || normalized === "cancelled" || normalized === "canceled") return "failed";
    return null;
};

const mapSessionRuntimeStatus = (input?: {
    status?: "idle" | "running" | "completed" | "failed" | "paused" | "cancelled" | "canceled";
    task_state?: "IDLE" | "RUNNING" | "PAUSED" | "SUCCEEDED" | "FAILED" | "CANCELED";
    session_control_state?: "IDLE" | "ACTIVE_RUNNING" | "ACTIVE_PAUSED" | "TERMINATING";
}): "idle" | "running" | "completed" | "failed" | null => {
    if (!input) return null;
    if (input.task_state === "RUNNING" || input.task_state === "PAUSED") return "running";
    if (input.task_state === "SUCCEEDED") return "completed";
    if (input.task_state === "FAILED" || input.task_state === "CANCELED") return "failed";
    if (input.session_control_state === "ACTIVE_RUNNING" || input.session_control_state === "ACTIVE_PAUSED" || input.session_control_state === "TERMINATING") {
        return "running";
    }
    if (input.status === "paused") return "running";
    if (input.status === "running") return "running";
    if (input.status === "completed") return "completed";
    if (input.status === "failed" || input.status === "cancelled" || input.status === "canceled") return "failed";
    return null;
};

export function useRunDetailState(): RunDetailState {
    const searchParams = useSearchParams();
    const searchParamsString = searchParams.toString();
    const sessionId = searchParams.get("session_id");
    const newSessionIntent = searchParams.get("new_session");
    const workflowIdParam = searchParams.get("workflow_id");
    const baseIsNewSession = (sessionId === "new" || !sessionId) && !workflowIdParam;
    const router = useRouter();
    const commands = useRunCommands();

    const [actualSessionId, setActualSessionId] = useState<string | null>(null);
    const [draftSessionId, setDraftSessionId] = useState<string>(() => createDraftSessionId());
    const isNewSession = baseIsNewSession && !actualSessionId;
    const resolvedSessionId = (sessionId && sessionId !== "new" ? sessionId : null) || actualSessionId;
    const actorSessionId = resolvedSessionId || draftSessionId;

    const [isLoading, setIsLoading] = useState(!baseIsNewSession);
    const [error, setError] = useState<string | null>(null);
    const [sessionData, setSessionData] = useState<SessionDataBundle | null>(null);
    const [sessionHistory, setSessionHistory] = useState<SessionHistoryData>(null);
    const [workspacePhase, setWorkspacePhase] = useState<"idle" | "clearing" | "loading" | "hydrated" | "empty" | "error">(
        isNewSession ? "idle" : "loading",
    );
    const [loadPhase, setLoadPhase] = useState<"idle" | "clearing" | "loading" | "hydrated" | "streaming">(
        baseIsNewSession ? "idle" : "loading",
    );
    const [activeTab, setActiveTab] = useState("conversation");
    const [isTimelineOpen, setIsTimelineOpen] = useState(false);
    const [showWorkspace, setShowWorkspace] = useState(true);
    const [workspaceExpanded, setWorkspaceExpanded] = useState(false);
    const [streamRestartKey, setStreamRestartKey] = useState(0);
    const [isPending, startTransition] = useTransition();
    const prevNewSessionIntentRef = useRef<string | null>(null);
    const redirectToAuth = useCallback(() => {
        const next = encodeURIComponent(`/run-detail?${searchParamsString}`);
        router.replace(`/runs?auth_required=1&next=${next}`);
    }, [router, searchParamsString]);
    const bundleLoaderActor = useMemo(() => {
        const actor = createActor(
            createSessionBundleLoaderMachine({
                loadBundle: async (bundleSessionId: string) => {
                    // Fetch session first so a missing/unauthorized session fails fast
                    // without fan-out 404 requests for dependent endpoints.
                    const session = await getSession(bundleSessionId);
                    const [conversation, timeline, history, state] = await Promise.all([
                        getSessionConversation(bundleSessionId),
                        getSessionTimeline(bundleSessionId, 500, 0, true),
                        getSessionHistory(bundleSessionId),
                        getSessionState(bundleSessionId),
                    ]);
                    return { session, conversation, timeline, history, state };
                },
            }),
        );
        actor.start();
        return actor;
    }, []);
    const workspaceLoaderActor = useMemo(() => {
        const actor = createActor(
            createWorkspaceLoaderMachine({
                loadWorkspace: async (workspaceSessionId: string) => {
                    const workspace = await getSessionWorkspace(workspaceSessionId);
                    const cards = Array.isArray(workspace.cards) ? workspace.cards : [];
                    const supportedQuestionTypes = Array.isArray(workspace.supported_question_types)
                        ? workspace.supported_question_types.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
                        : [];

                    return {
                        sessionId: workspace.session_id || workspaceSessionId,
                        cards,
                        projectionStatus: workspace.projection_status,
                        templateId: workspace.template_id,
                        supportedQuestionTypes,
                    };
                },
            }),
        );
        actor.start();
        return actor;
    }, []);

    const selectedAgent = useRunSelector((ctx) => ctx.selectedAgent);
    const researchStrategy = useRunSelector((ctx) => ctx.researchStrategy);
    const runSession = useRunSession(actorSessionId);

    const runEvents = runSession.events;
    const runMessages = runSession.messages;
    const runStatus = runSession.status;
    const runPhase = runSession.runPhase;
    const connectionState = runSession.connectionState;
    const streamError = runSession.streamError;
    const sessionTitle = runSession.sessionTitle;
    const isPaused = runSession.isPaused;
    const pauseCheckpoint = runSession.pauseCheckpoint;
    const isCancelling = runSession.isCancelling;
    const isCancelled = runSession.isCancelled;
    const cards = runSession.cards;
    const hasLiveRuntime = useMemo(
        () =>
            runSession.status === "running" ||
            runSession.runPhase === "streaming" ||
            runSession.connectionState === "connecting" ||
            runSession.connectionState === "connected" ||
            runSession.connectionState === "reconnecting" ||
            runSession.messages.some((message) => message.isGenerating),
        [runSession.connectionState, runSession.messages, runSession.runPhase, runSession.status],
    );

    const activeWorkflowId = runSession.mainWorkflowId || null;
    const timelineScrollRef = useRef<HTMLDivElement>(null);
    const conversationScrollRef = useRef<HTMLDivElement>(null);
    const userHasScrolledRef = useRef(false);

    const timelineStorageKey = useMemo(() => {
        if (!sessionId || sessionId === "new") return null;
        return `run-detail:timeline-open:${sessionId}`;
    }, [sessionId]);

    const workspaceExpandStorageKey = useMemo(() => {
        if (!sessionId || sessionId === "new") return null;
        return `run-detail:workspace-expanded:${sessionId}`;
    }, [sessionId]);

    useEffect(() => {
        if (sessionId !== "new") {
            prevNewSessionIntentRef.current = null;
            return;
        }

        const nextIntent = newSessionIntent || "__default__";
        if (prevNewSessionIntentRef.current === nextIntent) return;
        prevNewSessionIntentRef.current = nextIntent;

        const nextDraftSessionId = createDraftSessionId();
        setDraftSessionId(nextDraftSessionId);
        setActualSessionId(null);
        setSessionData(null);
        setSessionHistory(null);
        setWorkspacePhase("idle");
        setLoadPhase("idle");
        setIsLoading(false);
        setError(null);

        commands.activateSession(nextDraftSessionId);
        commands.resetSession(nextDraftSessionId);
    }, [commands, newSessionIntent, sessionId]);

    useEffect(() => {
        bundleLoaderActor.send({
            type: "SYNC_SESSION",
            sessionId: resolvedSessionId,
        });
    }, [bundleLoaderActor, resolvedSessionId]);
    useEffect(() => {
        workspaceLoaderActor.send({
            type: "SYNC_SESSION",
            sessionId: resolvedSessionId,
        });
    }, [resolvedSessionId, workspaceLoaderActor]);

    const bundleLoaderState = useActorSelector(bundleLoaderActor, (snapshot) => snapshot.value);
    const bundleData = useActorSelector(bundleLoaderActor, (snapshot) => snapshot.context.data);
    const bundleError = useActorSelector(bundleLoaderActor, (snapshot) => snapshot.context.error);
    const workspaceLoaderState = useActorSelector(workspaceLoaderActor, (snapshot) => snapshot.value);
    const workspaceData = useActorSelector(workspaceLoaderActor, (snapshot) => snapshot.context.data);

    useEffect(() => {
        commands.activateSession(actorSessionId);
    }, [actorSessionId, commands]);

    useEffect(() => {
        if (!resolvedSessionId) {
            setSessionData(null);
            setSessionHistory(null);
            return;
        }
        setSessionData(null);
        setSessionHistory(null);
    }, [resolvedSessionId]);

    useEffect(() => {
        if (!baseIsNewSession) return;
        const hasActiveContext = !!activeWorkflowId || runStatus === "running" || runMessages.length > 0 || runEvents.length > 0;
        if (hasActiveContext) return;
        commands.resetSession(actorSessionId);
        setSessionData(null);
        setSessionHistory(null);
        setWorkspacePhase("idle");
        setLoadPhase("idle");
        setIsLoading(false);
        setError(null);
    }, [activeWorkflowId, actorSessionId, baseIsNewSession, commands, runEvents.length, runMessages.length, runStatus]);

    useEffect(() => {
        if (!resolvedSessionId) return;
        if (bundleLoaderState === "loading") {
            setIsLoading(true);
            commands.setRunPhase(actorSessionId, "loading");
            setWorkspacePhase("loading");
        }
    }, [actorSessionId, bundleLoaderState, commands, resolvedSessionId]);

    useEffect(() => {
        if (!resolvedSessionId || !bundleData) return;
        if (bundleData.session.session_id !== resolvedSessionId) return;

        if (!hasLiveRuntime) {
            commands.resetSession(actorSessionId);
        }
        setSessionHistory(bundleData.history);
        setSessionData({
            conversation: bundleData.conversation,
            timeline: bundleData.timeline,
        });

        const isTemplateSession =
            bundleData.session.first_task_mode === "card_template" ||
            bundleData.session.is_research_session === true;
        const strategy = bundleData.session.research_strategy || "standard";
        commands.setSelectedAgent(isTemplateSession ? "card_template" : "normal");
        if (isTemplateSession) {
            commands.setResearchStrategy(strategy as "quick" | "standard" | "deep" | "academic");
        }

        if (!hasLiveRuntime) {
            (bundleData.timeline?.events || []).forEach((event) => {
                commands.addEvent(actorSessionId, { ...event, isHistorical: true } as RunEvent);
            });

            (bundleData.conversation?.messages || []).forEach((message, index) => {
                commands.addMessage(actorSessionId, {
                    id: message.id || `${message.role}-${index}`,
                    role: message.role || "assistant",
                    content: message.content || "",
                    timestamp: formatMessageTimestamp(message.timestamp),
                    taskId: message.task_id,
                    metadata: message.metadata,
                    attachments: normalizeMessageAttachments(message.attachments),
                });
            });
        }

        const latestTask = Array.isArray(bundleData.history?.tasks) && bundleData.history.tasks.length > 0
            ? bundleData.history.tasks[bundleData.history.tasks.length - 1]
            : null;
        const stateWorkflowId = normalizeWorkflowId(bundleData.state?.active_task_id);
        const latestWorkflowId = normalizeWorkflowId(latestTask?.workflow_id) || normalizeWorkflowId(latestTask?.task_id);
        const activeWorkflowFromBundle = stateWorkflowId || latestWorkflowId;
        if (activeWorkflowFromBundle) {
            commands.setMainWorkflowId(actorSessionId, activeWorkflowFromBundle);
            if (!hasLiveRuntime) {
                const mappedStatus = mapSessionRuntimeStatus(bundleData.state) || mapHistoryTaskStatus(latestTask?.status);
                if (mappedStatus) {
                    commands.setStatus(actorSessionId, mappedStatus);
                    commands.setRunPhase(actorSessionId, mappedStatus === "running" ? "streaming" : "hydrated");
                    if (mappedStatus === "running") {
                        commands.upsertMessage(actorSessionId, {
                            id: `generating-${activeWorkflowFromBundle}`,
                            role: "assistant",
                            content: "Generating...",
                            timestamp: new Date().toLocaleTimeString(),
                            isGenerating: true,
                            taskId: activeWorkflowFromBundle,
                        });
                    }
                }
                if (bundleData.state?.task_state === "PAUSED" || bundleData.state?.session_control_state === "ACTIVE_PAUSED") {
                    commands.setPaused(actorSessionId, true);
                } else if (bundleData.state?.task_state === "RUNNING" || bundleData.state?.session_control_state === "ACTIVE_RUNNING") {
                    commands.setPaused(actorSessionId, false);
                }
                if (bundleData.state?.session_control_state === "TERMINATING") {
                    commands.setCancelling(actorSessionId, true);
                }
            }
        }

        setWorkspacePhase("loading");
        setLoadPhase("hydrated");
        if (!hasLiveRuntime) {
            commands.setRunPhase(actorSessionId, "hydrated");
        }
        setError(null);
        setIsLoading(false);
    }, [actorSessionId, bundleData, commands, hasLiveRuntime, resolvedSessionId]);

    useEffect(() => {
        if (!resolvedSessionId) return;
        if (bundleLoaderState !== "failure") return;
        if (isUnauthenticatedApiError(bundleError)) {
            redirectToAuth();
            return;
        }
        setIsLoading(false);
        setError(toRunDetailErrorMessage(bundleError, "Failed to load session bundle"));
        commands.setRunPhase(actorSessionId, "error");
    }, [actorSessionId, bundleError, bundleLoaderState, commands, redirectToAuth, resolvedSessionId]);

    useEffect(() => {
        if (!resolvedSessionId || !workspaceData) return;
        if (workspaceData.sessionId !== resolvedSessionId) return;
        commands.setCards(actorSessionId, workspaceData.cards);
        const nextQuestionTypes = workspaceData.supportedQuestionTypes || [];
        const templatePreflight = runSession.templatePreflight;
        const nextTemplateId = workspaceData.templateId || templatePreflight.templateId;
        const shouldSyncQuestionTypes = nextQuestionTypes.length > 0 || templatePreflight.questionTypes.length === 0;
        const mergedQuestionTypes = shouldSyncQuestionTypes ? nextQuestionTypes : templatePreflight.questionTypes;
        const questionTypesUnchanged =
            mergedQuestionTypes.length === templatePreflight.questionTypes.length &&
            mergedQuestionTypes.every((item, index) => item === templatePreflight.questionTypes[index]);
        if (nextTemplateId !== templatePreflight.templateId || !questionTypesUnchanged) {
            commands.setTemplatePreflight(actorSessionId, {
                ...templatePreflight,
                templateId: nextTemplateId,
                questionTypes: mergedQuestionTypes,
                checkedAt: templatePreflight.checkedAt || new Date().toISOString(),
            });
        }
        setWorkspacePhase(inferWorkspacePhaseFromData(workspaceData));
    }, [actorSessionId, commands, resolvedSessionId, runSession.templatePreflight, workspaceData]);

    useEffect(() => {
        if (!resolvedSessionId) return;
        if (workspaceLoaderState !== "loading") return;
        if (workspacePhase === "clearing") return;
        if (workspaceData) return;
        setWorkspacePhase("loading");
    }, [resolvedSessionId, workspaceData, workspaceLoaderState, workspacePhase]);

    useEffect(() => {
        if (!resolvedSessionId) return;
        if (workspaceLoaderState !== "failure") return;
        setWorkspacePhase("error");
    }, [resolvedSessionId, workspaceLoaderState]);

    useEffect(() => {
        if (!resolvedSessionId) return;
        if (runStatus !== "running") return;
        const timer = window.setInterval(() => {
            workspaceLoaderActor.send({ type: "REFRESH" });
        }, 1500);
        return () => {
            window.clearInterval(timer);
        };
    }, [resolvedSessionId, runStatus, workspaceLoaderActor]);

    useEffect(() => {
        if (!resolvedSessionId) return;
        if (runStatus !== "completed") return;
        workspaceLoaderActor.send({ type: "REFRESH" });
    }, [resolvedSessionId, runStatus, workspaceLoaderActor]);

    useEffect(() => {
        if (!workflowIdParam) return;
        let cancelled = false;

        const initializeFromWorkflow = async () => {
            try {
                setIsLoading(true);
                const task = await getTask(workflowIdParam);
                if (cancelled) return;

                const workflowId = normalizeWorkflowId(task.workflow_id as string | undefined) || normalizeWorkflowId(workflowIdParam);
                if (!workflowId) {
                    throw new Error("Invalid workflow identifier");
                }

                commands.setMainWorkflowId(actorSessionId, workflowId);

                commands.addMessage(actorSessionId, {
                    id: `user-${workflowId}`,
                    role: "user",
                    content: task.query,
                    timestamp: new Date(task.created_at || Date.now()).toLocaleTimeString(),
                    taskId: workflowId,
                });

                if (task.status === "running" || task.status === "queued") {
                    commands.upsertMessage(actorSessionId, {
                        id: `generating-${workflowId}`,
                        role: "assistant",
                        content: "Generating...",
                        timestamp: new Date().toLocaleTimeString(),
                        isGenerating: true,
                        taskId: workflowId,
                    });
                    commands.setStatus(actorSessionId, "running");
                    commands.setRunPhase(actorSessionId, "streaming");
                    setLoadPhase("streaming");
                }

                if (task.session_id) {
                    if (!resolvedSessionId) {
                        commands.promoteSession(actorSessionId, task.session_id);
                    }
                    setActualSessionId(task.session_id);
                    if (!sessionId || sessionId === "new") {
                        const nextParams = new URLSearchParams(searchParamsString);
                        nextParams.set("session_id", task.session_id);
                        router.replace(`/run-detail?${nextParams.toString()}`);
                    }
                }
            } catch (err) {
                if (!cancelled) {
                    if (isUnauthenticatedApiError(err)) {
                        redirectToAuth();
                        return;
                    }
                    setError(toRunDetailErrorMessage(err, "Failed to load task"));
                }
            } finally {
                if (!cancelled) {
                    setIsLoading(false);
                }
            }
        };

        void initializeFromWorkflow();

        return () => {
            cancelled = true;
        };
    }, [actorSessionId, commands, redirectToAuth, resolvedSessionId, router, searchParamsString, sessionId, workflowIdParam]);

    const streamHandlers = useMemo(
        () => ({
            onConnectionState: (state: "idle" | "connecting" | "connected" | "reconnecting" | "error") => {
                commands.setConnectionState(actorSessionId, state);
            },
            onStreamError: (value: string | null) => {
                commands.setStreamError(actorSessionId, value);
            },
            onCardsBatch: (nextCards: CardData[]) => {
                commands.upsertCardsBatch(actorSessionId, nextCards);
            },
            onDomainEvent: (event: RunDomainEvent) => {
                const targetSessionId = actorSessionId;
                const projected = projectDomainEventToRunEvent(event);
                if (projected) {
                    commands.addEvent(targetSessionId, projected);
                }

                if (event.kind === "workflow.started") {
                    commands.setStatus(targetSessionId, "running");
                    commands.setRunPhase(targetSessionId, "streaming");
                    commands.upsertMessage(targetSessionId, {
                        id: `generating-${event.workflowId}`,
                        role: "assistant",
                        content: "Generating...",
                        timestamp: new Date().toLocaleTimeString(),
                        isGenerating: true,
                        taskId: event.workflowId,
                    });
                    return;
                }
                if (event.kind === "workflow.completed") {
                    commands.setStatus(targetSessionId, "completed");
                    commands.setRunPhase(targetSessionId, "hydrated");
                    commands.clearGeneratingMessages(targetSessionId, event.workflowId);
                    commands.clearStatusMessages(targetSessionId, event.workflowId);
                    return;
                }
                if (event.kind === "workflow.failed") {
                    commands.setStatus(targetSessionId, "failed");
                    commands.setRunPhase(targetSessionId, "error");
                    commands.clearGeneratingMessages(targetSessionId, event.workflowId);
                    commands.clearStatusMessages(targetSessionId, event.workflowId);
                    commands.setStreamError(targetSessionId, event.message);
                    return;
                }
                if (event.kind === "message.completed") {
                    if (!event.content.trim()) return;
                    commands.upsertMessage(targetSessionId, {
                        id: `assistant-${event.messageId || Date.now()}`,
                        role: "assistant",
                        content: event.content,
                        timestamp: new Date().toLocaleTimeString(),
                        taskId: event.workflowId || activeWorkflowId || undefined,
                        metadata: event.metadata,
                    });
                    return;
                }
                if (event.kind === "control.pause.confirmed") {
                    commands.setPaused(targetSessionId, true);
                    return;
                }
                if (event.kind === "control.resume.confirmed") {
                    commands.setPaused(targetSessionId, false);
                    return;
                }
                if (event.kind === "control.cancel.confirmed") {
                    commands.setCancelled(targetSessionId, true);
                    return;
                }
                if (event.kind === "control.rejected") {
                    commands.setStreamError(targetSessionId, event.message);
                    return;
                }
                if (event.kind === "timeline.event") {
                    const statusContent = (event.message && event.message.trim().length > 0)
                        ? event.message
                        : event.eventKind.replaceAll("_", " ").toLowerCase();
                    commands.upsertMessage(targetSessionId, {
                        id: `status-current-${event.workflowId}`,
                        role: "status",
                        content: statusContent,
                        timestamp: new Date(event.at).toLocaleTimeString(),
                        taskId: event.workflowId,
                        eventType: event.eventKind,
                    });
                    return;
                }
                if (event.kind === "workspace.updated") {
                    workspaceLoaderActor.send({ type: "REFRESH" });
                }
            },
        }),
        [activeWorkflowId, actorSessionId, commands, workspaceLoaderActor],
    );

    useRunStream(activeWorkflowId, streamHandlers, streamRestartKey);

    const handleTaskCreated = useCallback((newTaskId: string, query: string, workflowId?: string, newSessionId?: string, attachments?: Array<{fileId: string; filename: string; size: number; mimeType: string}>) => {
        const activeId = normalizeWorkflowId(workflowId) || normalizeWorkflowId(newTaskId);
        if (!activeId) {
            setError("Invalid workflow identifier");
            return;
        }

        commands.setMainWorkflowId(actorSessionId, activeId);
        commands.setStatus(actorSessionId, "running");
        commands.setRunPhase(actorSessionId, "streaming");
        commands.setCancelling(actorSessionId, false);
        commands.setCancelled(actorSessionId, false);
        commands.setPaused(actorSessionId, false);

        commands.addMessage(actorSessionId, {
            id: `user-${activeId}`,
            role: "user",
            content: query,
            timestamp: new Date().toLocaleTimeString(),
            taskId: activeId,
            attachments,
        });
        commands.upsertMessage(actorSessionId, {
            id: `generating-${activeId}`,
            role: "assistant",
            content: "Generating...",
            timestamp: new Date().toLocaleTimeString(),
            isGenerating: true,
            taskId: activeId,
        });

        setLoadPhase("streaming");
        if (newSessionId) {
            if (!resolvedSessionId) {
                commands.promoteSession(actorSessionId, newSessionId);
            }
            setActualSessionId(newSessionId);
            const nextParams = new URLSearchParams(searchParamsString);
            nextParams.set("session_id", newSessionId);
            router.replace(`/run-detail?${nextParams.toString()}`);
        }
    }, [actorSessionId, commands, resolvedSessionId, router, searchParamsString]);

    const handleFetchFinalOutputClick = useCallback(async () => {
        if (!activeWorkflowId) return;
        try {
            const task = await getTask(activeWorkflowId);
            if (task.status === "running" || task.status === "queued") {
                commands.setStatus(actorSessionId, "running");
                return;
            }
            if (task.status === "failed" || task.status === "cancelled") {
                commands.setStatus(actorSessionId, "failed");
                if (task.status === "cancelled") {
                    commands.setCancelled(actorSessionId, true);
                } else {
                    commands.setStreamError(actorSessionId, task.error_message || "Task failed");
                }
                return;
            }
            const raw = task.final_output || task.result;
            const content = typeof raw === "string" ? raw : raw ? JSON.stringify(raw) : "";
            if (!content.trim()) return;
            commands.clearGeneratingMessages(actorSessionId, activeWorkflowId);
            commands.upsertMessage(actorSessionId, {
                id: `assistant-final-${activeWorkflowId}`,
                role: "assistant",
                content,
                timestamp: new Date().toLocaleTimeString(),
                taskId: activeWorkflowId,
                metadata: task.metadata,
            });
            commands.setStatus(actorSessionId, "completed");
            commands.setStreamError(actorSessionId, null);
        } catch (err) {
            commands.setStreamError(actorSessionId, toRunDetailErrorMessage(err, "Failed to fetch final output"));
        }
    }, [activeWorkflowId, actorSessionId, commands]);

    const handleRetryStream = useCallback(() => {
        setStreamRestartKey((key) => key + 1);
    }, []);

    const { timelineEvents, scrollToMessage } = useTimeline({
        runEvents,
        currentTaskId: activeWorkflowId,
        setActiveTab,
        conversationScrollRef,
    });

    useScrollSync({
        timelineScrollRef,
        conversationScrollRef,
        timelineEvents,
        runStatus,
        messages: runMessages,
        activeTab,
        userHasScrolledRef,
    });

    const {
        isPauseLoading,
        isResumeLoading,
        canControlTask,
        handlePause,
        handleResume,
        handleCancel,
    } = useTaskControls({
        sessionId: actorSessionId,
        currentTaskId: activeWorkflowId,
        runStatus,
        isPaused,
        isCancelling,
    });

    useEffect(() => {
        if (!timelineStorageKey) {
            setIsTimelineOpen(false);
            return;
        }
        const stored = window.localStorage.getItem(timelineStorageKey);
        setIsTimelineOpen(stored === "true");
    }, [timelineStorageKey]);

    useEffect(() => {
        if (!timelineStorageKey) return;
        window.localStorage.setItem(timelineStorageKey, String(isTimelineOpen));
    }, [isTimelineOpen, timelineStorageKey]);

    useEffect(() => {
        if (!workspaceExpandStorageKey) {
            setWorkspaceExpanded(false);
            return;
        }
        const stored = window.localStorage.getItem(workspaceExpandStorageKey);
        setWorkspaceExpanded(stored === "true");
    }, [workspaceExpandStorageKey]);

    useEffect(() => {
        if (!workspaceExpandStorageKey) return;
        window.localStorage.setItem(workspaceExpandStorageKey, String(workspaceExpanded));
    }, [workspaceExpandStorageKey, workspaceExpanded]);

    const setSelectedAgentValue = useCallback((agent: "normal" | "card_template") => {
        commands.setSelectedAgent(agent);
    }, [commands]);

    const setResearchStrategyValue = useCallback((strategy: "quick" | "standard" | "deep" | "academic") => {
        commands.setResearchStrategy(strategy);
    }, [commands]);

    const showSoftLoading = (isPending || isLoading) && sessionId !== "new";

    return {
        sessionId,
        workflowIdParam,
        isNewSession,
        actualSessionId,
        resolvedSessionId,
        isLoading: showSoftLoading,
        error,
        messages: runMessages,
        runEvents,
        runStatus,
        runPhase,
        connectionState,
        streamError,
        sessionTitle,
        selectedAgent,
        researchStrategy,
        isPaused,
        pauseCheckpoint,
        isPauseLoading,
        isResumeLoading,
        canControlTask,
        isCancelling,
        isCancelled,
        cards,
        sessionData,
        sessionHistory,
        currentTaskId: activeWorkflowId,
        workspacePhase,
        loadPhase,
        activeTab,
        setActiveTab,
        isTimelineOpen,
        setIsTimelineOpen,
        showWorkspace,
        setShowWorkspace,
        workspaceExpanded,
        setWorkspaceExpanded,
        timelineEvents,
        conversationScrollRef,
        timelineScrollRef,
        handleRetryStream,
        handleFetchFinalOutputClick,
        handleTaskCreated,
        handlePause,
        handleResume,
        handleCancel,
        scrollToMessage,
        setSelectedAgentValue,
        setResearchStrategyValue,
        isPending,
        startTransition,
    };
}

"use client";

import { cancelTask, pauseTask, resumeTask } from "@/lib/kardcraft/api";
import { getSessionStreamState } from "@/lib/kardcraft/api";
import { getSessionWorkspace } from "@/lib/kardcraft/session-repository";
import type { RunEvent } from "@/lib/kardcraft/types";
import { useRegistryActor, useRegistryViewModel, useRunCommands, useSessionViewModel } from "@/lib/run/system";
import type { CardData, RunMessage } from "@/lib/run/types";
import { useRunDetailPreferencesStore } from "@/lib/ui/run-detail-preferences-store";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useTransition } from "react";
import { useScrollSync } from "./hooks/use-scroll-sync";
import { useTimeline } from "./hooks/use-timeline";
import { RunDetailActionsContext, type RunDetailActionsContextValue } from "./run-detail-actions-context";
import { deriveRunDetailControlState } from "./run-detail-control-state";
import { RunDetailDataContext, type RunDetailDataContextValue } from "./run-detail-data-context";
import { RunDetailUiContext, type RunDetailUiContextValue } from "./run-detail-ui-context";

const normalizeSessionId = (value: string | null | undefined): string | null => {
    if (typeof value !== "string") return null;
    const trimmed = value.trim();
    return trimmed.length > 0 && trimmed !== "new" ? trimmed : null;
};

type CardMedia = NonNullable<CardData["content"]["media"]>[number];

const asRecord = (value: unknown): Record<string, unknown> | null =>
    value && typeof value === "object" ? value as Record<string, unknown> : null;

const normalizeCardMedia = (value: unknown): CardMedia | null => {
    const record = asRecord(value);
    if (!record) return null;
    const fileId = typeof record.file_id === "string" ? record.file_id : "";
    const type = typeof record.type === "string" ? record.type : "";
    const url = typeof record.url === "string" ? record.url : "";
    if (!fileId || !type || !url) return null;
    return {
        file_id: fileId,
        type,
        url,
        meta: record.meta,
    };
};

export function RunDetailProvider({ children }: { children: React.ReactNode }) {
    const router = useRouter();
    const searchParams = useSearchParams();
    const sessionId = searchParams?.get("session_id") ?? null;
    const resolvedSessionId = normalizeSessionId(sessionId);
    const workflowIdParam = searchParams?.get("workflow_id") ?? null;

    const [isPending, startTransition] = useTransition();
    const view = useSessionViewModel(resolvedSessionId);
    const registry = useRegistryViewModel();
    const commands = useRunCommands();
    const controlState = useMemo(() => deriveRunDetailControlState(view.status), [view.status]);

    useEffect(() => {
        if (resolvedSessionId) {
            commands.activateSession(resolvedSessionId);
        }
    }, [commands, resolvedSessionId]);

    const bootstrapQuery = useQuery({
        queryKey: ["run-detail", "bootstrap", resolvedSessionId],
        queryFn: async () => {
            if (!resolvedSessionId) return null;
            const [streamState, workspace] = await Promise.all([
                getSessionStreamState(resolvedSessionId),
                getSessionWorkspace(resolvedSessionId),
            ]);
            return { streamState, workspace };
        },
        enabled: !!resolvedSessionId,
        staleTime: Infinity,
    });

    const registryActor = useRegistryActor();

    useEffect(() => {
        const data = bootstrapQuery.data;
        if (!data || !resolvedSessionId) return;

        const latestRun = data.streamState.runs.at(-1) ?? null;
        const workflowId = latestRun?.process_id || null;
        const runId = latestRun?.run_id || null;
        const conversationStatus = latestRun
            ? latestRun.status === "interrupted" ? "waiting_input"
                : latestRun.status === "completed" ? "completed"
                    : latestRun.status === "cancelled" ? "cancelled"
                        : latestRun.status === "error" ? "failed"
                            : "running"
            : "idle";

        // 从 conversation 恢复消息（需要转换字段名）
        const messages: RunMessage[] = data.streamState.messages.map((msg) => ({
            id: msg.message_id,
            role: msg.role,
            content: msg.content,
            timestamp: msg.completed_at || msg.created_at,
            taskId: msg.process_id,
            runId: msg.run_id,
            metadata: msg.metadata,
            attachments: msg.attachments?.map((att) => ({
                fileId: att.file_id,
                filename: att.filename,
                size: att.size,
                mimeType: att.mime_type,
            })),
        }));

        const chatEvents = new Set(["RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END", "RUN_FINISHED", "RUN_ERROR"]);
        const events: RunEvent[] = data.streamState.events
            .filter((event) => !chatEvents.has(event.event_type) && event.event_type !== "PLANNER_TRACE")
            .map((event) => ({
                id: event.sequence,
                type: event.event_type,
                workflow_id: event.process_id || workflowId || undefined,
                run_id: event.run_id,
                stream_id: event.event_id,
                timestamp: event.occurred_at,
                payload: event.payload,
                message: typeof event.payload.message === "string" ? event.payload.message : undefined,
            } as RunEvent));

        // 从 workspace 恢复卡片（需要转换字段名）
        const cards: CardData[] = (data.workspace?.cards || []).map((card) => ({
            ...card,
            content: {
                ...card.content,
                media: card.content.media
                    ?.map((item) => normalizeCardMedia(item))
                    .filter((item): item is CardMedia => item !== null),
            },
        }));

        // 恢复会话状态
        commands.hydrateSession(resolvedSessionId, {
            workflowId,
            runId,
            messages,
            events,
            cards,
            cursor: data.streamState.cursor,
            interrupt: latestRun?.interrupt || null,
            state: { conversation_status: conversationStatus },
        });
    }, [bootstrapQuery.data, resolvedSessionId, commands]);

    const reconciledTerminalRef = useRef<string | null>(null);
    useEffect(() => {
        if (!resolvedSessionId) return;
        const shouldReconcile = view.status === "completed" || view.status === "failed" || view.status === "cancelled" || view.status === "waiting_input" || view.connectionState === "error";
        if (!shouldReconcile) return;
        const key = `${view.runId || "none"}:${view.status}:${view.connectionState}`;
        if (reconciledTerminalRef.current === key) return;
        reconciledTerminalRef.current = key;
        void bootstrapQuery.refetch();
    }, [bootstrapQuery, resolvedSessionId, view.connectionState, view.runId, view.status]);

    const uiPreferenceSessionKey = useMemo(() => resolvedSessionId ?? "new:default", [resolvedSessionId]);
    const persistedActiveTab = useRunDetailPreferencesStore((s) => s.activeTabBySession[uiPreferenceSessionKey] || "conversation");
    const persistedTimelineOpen = useRunDetailPreferencesStore((s) => s.timelineOpenBySession[uiPreferenceSessionKey] || false);
    const persistedWorkspaceExpanded = useRunDetailPreferencesStore((s) => s.workspaceExpandedBySession[uiPreferenceSessionKey] || false);
    const showWorkspace = useRunDetailPreferencesStore((s) => s.showWorkspace);
    const setPersistedActiveTab = useRunDetailPreferencesStore((s) => s.setActiveTab);
    const setPersistedTimelineOpen = useRunDetailPreferencesStore((s) => s.setTimelineOpen);
    const setPersistedWorkspaceExpanded = useRunDetailPreferencesStore((s) => s.setWorkspaceExpanded);
    const setPersistedShowWorkspace = useRunDetailPreferencesStore((s) => s.setShowWorkspace);

    const setActiveTab = useCallback((value: string) => setPersistedActiveTab(uiPreferenceSessionKey, value), [setPersistedActiveTab, uiPreferenceSessionKey]);
    const setIsTimelineOpen = useCallback((open: boolean) => setPersistedTimelineOpen(uiPreferenceSessionKey, open), [setPersistedTimelineOpen, uiPreferenceSessionKey]);
    const setWorkspaceExpanded = useCallback((expanded: boolean) => setPersistedWorkspaceExpanded(uiPreferenceSessionKey, expanded), [setPersistedWorkspaceExpanded, uiPreferenceSessionKey]);
    const setShowWorkspace = useCallback((show: boolean) => setPersistedShowWorkspace(show), [setPersistedShowWorkspace]);

    const timelineScrollRef = useRef<HTMLDivElement>(null);
    const conversationScrollRef = useRef<HTMLDivElement>(null);
    const userHasScrolledRef = useRef(false);

    const { timelineEvents, scrollToMessage } = useTimeline({
        runEvents: view.events,
        currentWorkflowId: view.workflowId,
        setActiveTab,
        conversationScrollRef,
    });

    useScrollSync({
        timelineScrollRef,
        conversationScrollRef,
        timelineEvents,
        runStatus: view.status,
        messages: view.messages,
        activeTab: persistedActiveTab,
        userHasScrolledRef,
    });

    const handleTaskCreated = useCallback(
        (workflowId: string, query: string, newSessionId?: string, attachments?: Array<{ fileId: string; filename: string; size: number; mimeType: string }>, runId?: string, cursor?: number, serverUserMessage?: import("@/lib/kardcraft/api").ConversationThreadMessage) => {
            const normalizedWorkflow = workflowId.trim();
            if (!normalizedWorkflow) return;

            console.log('[handleTaskCreated]', { workflowId, query, newSessionId, resolvedSessionId });

            if (newSessionId && !resolvedSessionId) {
                const nextParams = new URLSearchParams(searchParams?.toString() ?? "");
                nextParams.set("session_id", newSessionId);
                nextParams.set("workflow_id", normalizedWorkflow);
                router.replace(`/run-detail?${nextParams.toString()}`);
            }

            const targetSessionId = newSessionId || resolvedSessionId;
            if (targetSessionId) {
                console.log('[handleTaskCreated] activating/creating task for', { targetSessionId });
                commands.activateSession(targetSessionId);
                const userMessage: RunMessage | undefined = serverUserMessage ? {
                    id: serverUserMessage.message_id,
                    role: serverUserMessage.role,
                    content: serverUserMessage.content,
                    timestamp: serverUserMessage.completed_at || serverUserMessage.created_at,
                    taskId: serverUserMessage.process_id,
                    runId: serverUserMessage.run_id,
                    metadata: serverUserMessage.metadata,
                    attachments: serverUserMessage.attachments?.map((item) => ({
                        fileId: item.file_id, filename: item.filename, size: item.size, mimeType: item.mime_type,
                    })),
                } : undefined;
                commands.createTask(targetSessionId, normalizedWorkflow, query, runId, cursor, userMessage);

                // Debug: check session state immediately after create
                const snap = registryActor.getSnapshot().context.sessions[targetSessionId]?.getSnapshot();
                console.log('[handleTaskCreated] post-create session state:', {
                    status: snap?.context.status,
                    messagesCount: snap?.context.messages.length,
                    hasGenerating: snap?.context.messages.some((message) => message.isGenerating),
                    runPhase: snap?.context.runPhase,
                });
            }
        },
        [commands, registryActor, resolvedSessionId, router, searchParams],
    );

    const handlePause = useCallback(async () => {
        const workflowId = view.workflowId;
        if (!workflowId || !resolvedSessionId) return;
        
        commands.pauseSession(resolvedSessionId);
        
        try {
            await pauseTask(workflowId);
        } catch (error) {
            console.error('[handlePause] Failed:', error);
            commands.rejectControl(resolvedSessionId, 'pause', error instanceof Error ? error.message : 'Failed to pause task');
        }
    }, [commands, resolvedSessionId, view.workflowId]);

    const handleResume = useCallback(async () => {
        const workflowId = view.workflowId;
        if (!workflowId || !resolvedSessionId) return;
        
        commands.resumeSession(resolvedSessionId);
        
        try {
            await resumeTask(workflowId);
        } catch (error) {
            console.error('[handleResume] Failed:', error);
            commands.rejectControl(resolvedSessionId, 'resume', error instanceof Error ? error.message : 'Failed to resume task');
        }
    }, [commands, resolvedSessionId, view.workflowId]);

    const handleCancel = useCallback(async () => {
        const workflowId = view.workflowId;
        if (!workflowId || !resolvedSessionId) return;
        
        commands.cancelSession(resolvedSessionId);
        
        try {
            await cancelTask(workflowId);
        } catch (error) {
            console.error('[handleCancel] Failed:', error);
            commands.rejectControl(resolvedSessionId, 'cancel', error instanceof Error ? error.message : 'Failed to cancel task');
        }
    }, [commands, resolvedSessionId, view.workflowId]);

    const dataValue = useMemo<RunDetailDataContextValue>(
        () => ({
            sessionId,
            workflowIdParam,
            isNewSession: !resolvedSessionId,
            actualSessionId: view.sessionId,
            resolvedSessionId: view.sessionId ?? resolvedSessionId,
            isLoading: bootstrapQuery.isLoading || (isPending && sessionId !== "new"),
            error: bootstrapQuery.error instanceof Error ? bootstrapQuery.error.message : null,
            messages: view.messages,
            runEvents: view.events,
            runStatus: view.status,
            runPhase: view.runPhase,
            connectionState: view.connectionState,
            streamError: view.streamError,
            sessionTitle: null,
            selectedAgent: registry.selectedAgent,
            researchStrategy: registry.researchStrategy,
            isPaused: view.isPaused,
            pauseCheckpoint: view.pauseCheckpoint ? JSON.stringify(view.pauseCheckpoint) : null,
            isControlSessionActive: controlState.isControlSessionActive,
            isPauseLoading: controlState.isPauseLoading,
            isResumeLoading: controlState.isResumeLoading,
            showPause: controlState.showPause,
            showResume: controlState.showResume,
            showCancel: controlState.showCancel,
            inputDisabled: controlState.inputDisabled,
            canControlTask: !!view.workflowId,
            isCancelling: view.isCancelling,
            isCancelled: view.isCancelled,
            cards: view.cards,
            sessionData: null,
            sessionHistory: null,
            currentWorkflowId: view.workflowId,
            currentRunId: view.runId,
            interruptId: view.interrupt?.interrupt_id || null,
            timelineEvents,
            workspacePhase: (view.cards.length > 0 ? "hydrated" : "empty"),
            loadPhase: view.runPhase === "error" ? "loading" : view.runPhase,
        }),
        [
            sessionId,
            workflowIdParam,
            resolvedSessionId,
            view,
            bootstrapQuery.isLoading,
            bootstrapQuery.error,
            bootstrapQuery.data,
            isPending,
            registry.selectedAgent,
            registry.researchStrategy,
            controlState,
            timelineEvents,
        ],
    );

    const uiValue = useMemo<RunDetailUiContextValue>(
        () => ({
            activeTab: persistedActiveTab,
            setActiveTab,
            isTimelineOpen: persistedTimelineOpen,
            setIsTimelineOpen,
            showWorkspace,
            setShowWorkspace,
            workspaceExpanded: persistedWorkspaceExpanded,
            setWorkspaceExpanded,
            conversationScrollRef,
            timelineScrollRef,
        }),
        [
            persistedActiveTab,
            setActiveTab,
            persistedTimelineOpen,
            setIsTimelineOpen,
            showWorkspace,
            setShowWorkspace,
            persistedWorkspaceExpanded,
            setWorkspaceExpanded,
        ],
    );

    const actionsValue = useMemo<RunDetailActionsContextValue>(
        () => ({
            handleRetryStream: () => {
                console.warn('[handleRetryStream] Not implemented in V2');
            },
            handleTaskCreated,
            handlePause,
            handleResume,
            handleCancel,
            scrollToMessage,
            setSelectedAgentValue: (agent) => commands.setSelectedAgent(agent),
            setResearchStrategyValue: (strategy) => commands.setResearchStrategy(strategy),
            startTransition,
        }),
        [commands, handleTaskCreated, handlePause, handleResume, handleCancel, scrollToMessage, startTransition],
    );

    return (
        <Suspense fallback={<div>Loading…</div>}>
            <RunDetailDataContext.Provider value={dataValue}>
                <RunDetailUiContext.Provider value={uiValue}>
                    <RunDetailActionsContext.Provider value={actionsValue}>{children}</RunDetailActionsContext.Provider>
                </RunDetailUiContext.Provider>
            </RunDetailDataContext.Provider>
        </Suspense>
    );
}

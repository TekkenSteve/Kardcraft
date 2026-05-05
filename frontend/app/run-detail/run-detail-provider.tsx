"use client";

import { cancelTask, pauseTask, resumeTask } from "@/lib/kardcraft/api";
import { getSessionConversation, getSessionHistory, getSessionState, getSessionTimeline, getSessionWorkspace } from "@/lib/kardcraft/session-repository";
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
            const [conversation, timeline, history, state, workspace] = await Promise.all([
                getSessionConversation(resolvedSessionId),
                getSessionTimeline(resolvedSessionId, 500, 0, true),
                getSessionHistory(resolvedSessionId),
                getSessionState(resolvedSessionId),
                getSessionWorkspace(resolvedSessionId),
            ]);
            return { conversation, timeline, history, state, workspace };
        },
        enabled: !!resolvedSessionId,
        staleTime: Infinity,
    });

    // 跟踪是否已经 hydrated，避免重复
    const hydratedSessionsRef = useRef<Set<string>>(new Set());
    const registryActor = useRegistryActor();

    useEffect(() => {
        const data = bootstrapQuery.data;
        if (!data || !resolvedSessionId) return;

        // 如果已经 hydrated 过这个 session，跳过
        if (hydratedSessionsRef.current.has(resolvedSessionId)) {
            console.log('[Provider] Session already hydrated, skipping:', resolvedSessionId);
            return;
        }

        // 检查 session 是否已由 createTask 启动（用户刚发送消息）
        // 如果 session 已处于 running 且有消息，说明是刚创建的任务，不需要用 DB 数据覆盖
        const existingSession = registryActor.getSnapshot().context.sessions[resolvedSessionId];
        if (existingSession) {
            const snap = existingSession.getSnapshot();
            if (snap.context.status === 'running' && snap.context.messages.length > 0) {
                console.log('[Provider] Session already running with messages, skip hydration (freshly created task)');
                hydratedSessionsRef.current.add(resolvedSessionId);
                return;
            }
        }

        console.log('[Provider] Hydrating session:', resolvedSessionId);
        hydratedSessionsRef.current.add(resolvedSessionId);

        // 从数据库恢复状态
        const state = data.state;
        const workflowId = state?.active_task_id || null;
        const runId = workflowId;

        console.log('[Provider] Hydrate data:', { workflowId, runId, messagesCount: data.conversation?.messages?.length, cardsCount: data.workspace?.cards?.length });

        // 从 conversation 恢复消息（需要转换字段名）
        const messages: RunMessage[] = (data.conversation?.messages || []).map((msg) => ({
            id: msg.id,
            role: msg.role,
            content: msg.content,
            timestamp: msg.timestamp,
            taskId: msg.task_id,
            metadata: msg.metadata,
            attachments: msg.attachments?.map((att) => ({
                fileId: att.file_id,
                filename: att.filename,
                size: att.size,
                mimeType: att.mime_type,
            })),
        }));

        const events: RunEvent[] = (data.timeline?.events || []).map((event) => {
            const eventRecord = event as typeof event & { run_id?: string };
            return {
                ...event,
                workflow_id: event.workflow_id || event.task_id || workflowId || undefined,
                run_id: eventRecord.run_id || runId || undefined,
                timestamp: event.timestamp || new Date().toISOString(),
            } as RunEvent;
        });

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
            state: state
                ? {
                    active_task_id: state.active_task_id,
                    task_state: state.task_state,
                    session_control_state: state.session_control_state,
                }
                : null,
        });

        console.log('[Provider] Hydration complete');
    }, [bootstrapQuery.data, resolvedSessionId, commands, registryActor]);

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
        (workflowId: string, query: string, newSessionId?: string, attachments?: Array<{ fileId: string; filename: string; size: number; mimeType: string }>, runId?: string) => {
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
                commands.createTask(targetSessionId, normalizedWorkflow, query, runId);

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
            sessionData: bootstrapQuery.data
                ? { conversation: bootstrapQuery.data.conversation, timeline: bootstrapQuery.data.timeline }
                : null,
            sessionHistory: bootstrapQuery.data?.history || null,
            currentWorkflowId: view.workflowId,
            currentRunId: view.runId,
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

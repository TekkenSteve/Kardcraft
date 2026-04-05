"use client";

import { Suspense, useMemo } from "react";
import { RunDetailState, useRunDetailState } from "./hooks/use-run-detail-state";
import { RunDetailDataContext, RunDetailDataContextValue } from "./run-detail-data-context";
import { RunDetailUiContext, RunDetailUiContextValue } from "./run-detail-ui-context";
import { RunDetailActionsContext, RunDetailActionsContextValue } from "./run-detail-actions-context";

export function RunDetailProvider({ children }: { children: React.ReactNode }) {
    const state = useRunDetailState();

    const dataValue = useMemo<RunDetailDataContextValue>(() => ({
        sessionId: state.sessionId,
        workflowIdParam: state.workflowIdParam,
        isNewSession: state.isNewSession,
        actualSessionId: state.actualSessionId,
        resolvedSessionId: state.resolvedSessionId,
        isLoading: state.isLoading,
        error: state.error,
        messages: state.messages,
        runEvents: state.runEvents,
        runStatus: state.runStatus,
        runPhase: state.runPhase,
        connectionState: state.connectionState,
        streamError: state.streamError,
        sessionTitle: state.sessionTitle,
        selectedAgent: state.selectedAgent,
        researchStrategy: state.researchStrategy,
        isPaused: state.isPaused,
        pauseCheckpoint: state.pauseCheckpoint,
        isPauseLoading: state.isPauseLoading,
        isResumeLoading: state.isResumeLoading,
        canControlTask: state.canControlTask,
        isCancelling: state.isCancelling,
        isCancelled: state.isCancelled,
        cards: state.cards,
        sessionData: state.sessionData,
        sessionHistory: state.sessionHistory,
        currentTaskId: state.currentTaskId,
        timelineEvents: state.timelineEvents,
        workspacePhase: state.workspacePhase,
        loadPhase: state.loadPhase,
    }), [
        state.sessionId,
        state.workflowIdParam,
        state.isNewSession,
        state.actualSessionId,
        state.resolvedSessionId,
        state.isLoading,
        state.error,
        state.messages,
        state.runEvents,
        state.runStatus,
        state.runPhase,
        state.connectionState,
        state.streamError,
        state.sessionTitle,
        state.selectedAgent,
        state.researchStrategy,
        state.isPaused,
        state.pauseCheckpoint,
        state.isPauseLoading,
        state.isResumeLoading,
        state.canControlTask,
        state.isCancelling,
        state.isCancelled,
        state.cards,
        state.sessionData,
        state.sessionHistory,
        state.currentTaskId,
        state.timelineEvents,
        state.workspacePhase,
        state.loadPhase,
    ]);

    const uiValue = useMemo<RunDetailUiContextValue>(() => ({
        activeTab: state.activeTab,
        setActiveTab: state.setActiveTab,
        isTimelineOpen: state.isTimelineOpen,
        setIsTimelineOpen: state.setIsTimelineOpen,
        showWorkspace: state.showWorkspace,
        setShowWorkspace: state.setShowWorkspace,
        workspaceExpanded: state.workspaceExpanded,
        setWorkspaceExpanded: state.setWorkspaceExpanded,
        conversationScrollRef: state.conversationScrollRef,
        timelineScrollRef: state.timelineScrollRef,
    }), [
        state.activeTab,
        state.setActiveTab,
        state.isTimelineOpen,
        state.setIsTimelineOpen,
        state.showWorkspace,
        state.setShowWorkspace,
        state.workspaceExpanded,
        state.setWorkspaceExpanded,
        state.conversationScrollRef,
        state.timelineScrollRef,
    ]);

    const actionsValue = useMemo<RunDetailActionsContextValue>(() => ({
        handleRetryStream: state.handleRetryStream,
        handleFetchFinalOutputClick: state.handleFetchFinalOutputClick,
        handleTaskCreated: state.handleTaskCreated,
        handlePause: state.handlePause,
        handleResume: state.handleResume,
        handleCancel: state.handleCancel,
        scrollToMessage: state.scrollToMessage,
        setSelectedAgentValue: state.setSelectedAgentValue,
        setResearchStrategyValue: state.setResearchStrategyValue,
        startTransition: state.startTransition,
    }), [
        state.handleRetryStream,
        state.handleFetchFinalOutputClick,
        state.handleTaskCreated,
        state.handlePause,
        state.handleResume,
        state.handleCancel,
        state.scrollToMessage,
        state.setSelectedAgentValue,
        state.setResearchStrategyValue,
        state.startTransition,
    ]);

    return (
        <Suspense fallback={<div>Loading…</div>}>
            <RunDetailDataContext.Provider value={dataValue}>
                <RunDetailUiContext.Provider value={uiValue}>
                    <RunDetailActionsContext.Provider value={actionsValue}>
                        {children}
                    </RunDetailActionsContext.Provider>
                </RunDetailUiContext.Provider>
            </RunDetailDataContext.Provider>
        </Suspense>
    );
}

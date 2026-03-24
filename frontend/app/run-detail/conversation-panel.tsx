"use client";

import { ScrollArea } from "@/components/ui/scroll-area";
import { RunConversation } from "@/components/run-conversation";
import { ChatInput } from "@/components/chat-input";
import { useRunDetailData, useRunDetailActions, useRunDetailUi } from "./run-detail-hooks";

export function ConversationPanel() {
    const {
        messages,
        selectedAgent,
        researchStrategy,
        runStatus,
        isPaused,
        isPauseLoading,
        isResumeLoading,
        isCancelling,
        isNewSession,
        sessionId,
        resolvedSessionId,
        currentTaskId,
    } = useRunDetailData();
    const { conversationScrollRef } = useRunDetailUi();
    const {
        handleTaskCreated,
        handlePause,
        handleResume,
        handleCancel,
        setSelectedAgentValue,
    } = useRunDetailActions();

    if (messages.length > 0) {
        return (
            <>
                <div className="flex-1 min-h-0">
                    <ScrollArea className="h-full" ref={conversationScrollRef}>
                        <RunConversation messages={messages} agentType={selectedAgent} />
                    </ScrollArea>
                </div>
                <div className="border-t bg-background p-4 shrink-0">
                    <ChatInput
                        sessionId={isNewSession ? undefined : resolvedSessionId ?? undefined}
                        disabled={runStatus === "running"}
                        isTaskComplete={runStatus !== "running"}
                        selectedAgent={selectedAgent}
                        onSelectedAgentChange={(agent) => setSelectedAgentValue(agent)}
                        initialResearchStrategy={researchStrategy}
                        onTaskCreated={handleTaskCreated}
                        currentTaskId={currentTaskId}
                        isTaskRunning={runStatus === "running"}
                        isPaused={isPaused}
                        isPauseLoading={isPauseLoading}
                        isResumeLoading={isResumeLoading}
                        isCancelling={isCancelling}
                        onPause={handlePause}
                        onResume={handleResume}
                        onCancel={handleCancel}
                    />
                </div>
            </>
        );
    }

    return (
        <ChatInput
            sessionId={isNewSession ? undefined : resolvedSessionId ?? undefined}
            disabled={runStatus === "running"}
            isTaskComplete={runStatus !== "running"}
            selectedAgent={selectedAgent}
            onSelectedAgentChange={(agent) => setSelectedAgentValue(agent)}
            initialResearchStrategy={researchStrategy}
            onTaskCreated={handleTaskCreated}
            currentTaskId={currentTaskId}
            variant="centered"
            isTaskRunning={runStatus === "running"}
            isPaused={isPaused}
            isPauseLoading={isPauseLoading}
            isResumeLoading={isResumeLoading}
            isCancelling={isCancelling}
            onPause={handlePause}
            onResume={handleResume}
            onCancel={handleCancel}
        />
    );
}

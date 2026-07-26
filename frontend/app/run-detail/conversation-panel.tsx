"use client";

import { ScrollArea } from "@/components/ui/scroll-area";
import { RunConversation } from "@/components/run-conversation";
import { ChatInput } from "@/components/chat-input";
import type { UploadedFile } from "@/lib/file-upload/types";
import { useState } from "react";
import { useRunDetailData, useRunDetailActions, useRunDetailUi } from "./run-detail-hooks";

export function ConversationPanel() {
    const {
        messages,
        selectedAgent,
        researchStrategy,
        runStatus,
        isPaused,
        isControlSessionActive,
        isPauseLoading,
        isResumeLoading,
        showPause,
        showResume,
        showCancel,
        inputDisabled,
        canControlTask,
        isCancelling,
        isNewSession,
        resolvedSessionId,
        currentWorkflowId,
        currentRunId,
        interruptId,
    } = useRunDetailData();
    const { conversationScrollRef } = useRunDetailUi();
    const {
        handleTaskCreated,
        handlePause,
        handleResume,
        handleCancel,
        setSelectedAgentValue,
    } = useRunDetailActions();
    const showTaskControls = isControlSessionActive;
    const hasCurrentAssistantOverlay = messages.some((message) =>
        message.role === "assistant" &&
        message.isStreaming &&
        (!currentRunId || message.runId === currentRunId)
    );
    const isWaitingForAssistant =
        (runStatus === "running" || runStatus === "resuming") &&
        !hasCurrentAssistantOverlay;
    const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);

    return (
        <>
            {(messages.length > 0 || showTaskControls) && (
            <div className="flex-1 min-h-0">
                <ScrollArea className="h-full" ref={conversationScrollRef}>
                    <RunConversation
                        messages={messages}
                        agentType={selectedAgent}
                        isWaitingForAssistant={isWaitingForAssistant}
                    />
                </ScrollArea>
            </div>
            )}
            <div className={(messages.length > 0 || showTaskControls) ? "border-t bg-background p-4 shrink-0" : "flex-1 bg-background"}>
                <ChatInput
                    sessionId={isNewSession ? undefined : resolvedSessionId ?? undefined}
                    disabled={inputDisabled}
                    isTaskComplete={!showTaskControls}
                    selectedAgent={selectedAgent}
                    onSelectedAgentChange={(agent) => setSelectedAgentValue(agent)}
                    initialResearchStrategy={researchStrategy}
                    onTaskCreated={handleTaskCreated}
                    currentWorkflowId={currentWorkflowId}
                    interruptId={interruptId}
                    variant={(messages.length > 0 || showTaskControls) ? "default" : "centered"}
                    isTaskRunning={showTaskControls}
                    isPaused={isPaused}
                    isPauseLoading={isPauseLoading}
                    isResumeLoading={isResumeLoading}
                    showPause={showPause}
                    showResume={showResume}
                    showCancel={showCancel}
                    canControlTask={canControlTask}
                    isCancelling={isCancelling}
                    onPause={handlePause}
                    onResume={handleResume}
                    onCancel={handleCancel}
                    uploadedFiles={uploadedFiles}
                    onUploadedFilesChange={setUploadedFiles}
                />
            </div>
        </>
    );
}

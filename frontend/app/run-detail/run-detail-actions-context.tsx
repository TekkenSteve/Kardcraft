"use client";

import { createContext, useContext } from "react";

export interface RunDetailActionsContextValue {
    handleRetryStream: () => void;
    handleFetchFinalOutputClick: () => void;
    handleTaskCreated: (newTaskId: string, query: string, workflowId?: string, newSessionId?: string) => void;
    handlePause: () => void;
    handleResume: () => void;
    handleCancel: () => void;
    scrollToMessage: (messageId: string) => void;
    setSelectedAgentValue: (agent: "normal" | "card_template") => void;
    setResearchStrategyValue: (strategy: "quick" | "standard" | "deep" | "academic") => void;
    startTransition: (cb: () => void) => void;
}

const RunDetailActionsContext = createContext<RunDetailActionsContextValue | null>(null);

export function useRunDetailActions(): RunDetailActionsContextValue {
    const ctx = useContext(RunDetailActionsContext);
    if (!ctx) {
        throw new Error("useRunDetailActions must be used within RunDetailProvider");
    }
    return ctx;
}

export { RunDetailActionsContext };

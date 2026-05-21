"use client";

import { createContext, use } from "react";
import { SessionDataBundle, SessionHistoryData } from "./run-detail-types";
import { RunMessage, CardData } from "@/lib/run/types";
import { RunEvent } from "@/lib/kardcraft/types";
import { TimelineDisplayEvent } from "./hooks/use-timeline";

export interface RunDetailDataContextValue {
    sessionId: string | null;
    workflowIdParam: string | null;
    isNewSession: boolean;
    actualSessionId: string | null;
    resolvedSessionId: string | null;
    isLoading: boolean;
    error: string | null;
    messages: RunMessage[];
    runEvents: RunEvent[];
    runStatus: "idle" | "running" | "pausing" | "paused" | "resuming" | "cancelling" | "cancelled" | "completed" | "failed";
    runPhase: "idle" | "clearing" | "loading" | "hydrated" | "streaming" | "error";
    connectionState: "idle" | "connecting" | "connected" | "reconnecting" | "error";
    streamError: string | null;
    sessionTitle: string | null;
    selectedAgent: "normal" | "card_template";
    researchStrategy: "quick" | "standard" | "deep" | "academic";
    isPaused: boolean;
    pauseCheckpoint: string | null;
    isControlSessionActive: boolean;
    isPauseLoading: boolean;
    isResumeLoading: boolean;
    showPause: boolean;
    showResume: boolean;
    showCancel: boolean;
    inputDisabled: boolean;
    canControlTask: boolean;
    isCancelling: boolean;
    isCancelled: boolean;
    cards: CardData[];
    sessionData: SessionDataBundle | null;
    sessionHistory: SessionHistoryData;
    currentWorkflowId: string | null;
    currentRunId: string | null;
    timelineEvents: TimelineDisplayEvent[];
    workspacePhase: "idle" | "clearing" | "loading" | "hydrated" | "empty" | "error";
    loadPhase: "idle" | "clearing" | "loading" | "hydrated" | "streaming";
}

const RunDetailDataContext = createContext<RunDetailDataContextValue | null>(null);

export function useRunDetailData(): RunDetailDataContextValue {
    const ctx = use(RunDetailDataContext);
    if (!ctx) {
        throw new Error("useRunDetailData must be used within RunDetailProvider");
    }
    return ctx;
}

export { RunDetailDataContext };

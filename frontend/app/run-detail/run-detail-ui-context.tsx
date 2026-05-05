"use client";

import { createContext, useContext } from "react";

export interface RunDetailUiContextValue {
    activeTab: string;
    setActiveTab: (value: string) => void;
    isTimelineOpen: boolean;
    setIsTimelineOpen: (open: boolean) => void;
    showWorkspace: boolean;
    setShowWorkspace: (show: boolean) => void;
    workspaceExpanded: boolean;
    setWorkspaceExpanded: (expanded: boolean) => void;
    conversationScrollRef: React.RefObject<HTMLDivElement | null>;
    timelineScrollRef: React.RefObject<HTMLDivElement | null>;
}

const RunDetailUiContext = createContext<RunDetailUiContextValue | null>(null);

export function useRunDetailUi(): RunDetailUiContextValue {
    const ctx = useContext(RunDetailUiContext);
    if (!ctx) {
        throw new Error("useRunDetailUi must be used within RunDetailProvider");
    }
    return ctx;
}

export { RunDetailUiContext };

"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

type RunDetailPreferencesState = {
    activeTabBySession: Record<string, string>;
    timelineOpenBySession: Record<string, boolean>;
    workspaceExpandedBySession: Record<string, boolean>;
    showWorkspace: boolean;
    setActiveTab: (sessionKey: string, value: string) => void;
    setTimelineOpen: (sessionKey: string, open: boolean) => void;
    setWorkspaceExpanded: (sessionKey: string, expanded: boolean) => void;
    setShowWorkspace: (show: boolean) => void;
};

const DEFAULT_ACTIVE_TAB = "conversation";

export const useRunDetailPreferencesStore = create<RunDetailPreferencesState>()(
    persist(
        (set) => ({
            activeTabBySession: {},
            timelineOpenBySession: {},
            workspaceExpandedBySession: {},
            showWorkspace: true,
            setActiveTab: (sessionKey, value) =>
                set((state) => ({
                    activeTabBySession: {
                        ...state.activeTabBySession,
                        [sessionKey]: value || DEFAULT_ACTIVE_TAB,
                    },
                })),
            setTimelineOpen: (sessionKey, open) =>
                set((state) => ({
                    timelineOpenBySession: {
                        ...state.timelineOpenBySession,
                        [sessionKey]: open,
                    },
                })),
            setWorkspaceExpanded: (sessionKey, expanded) =>
                set((state) => ({
                    workspaceExpandedBySession: {
                        ...state.workspaceExpandedBySession,
                        [sessionKey]: expanded,
                    },
                })),
            setShowWorkspace: (show) => set(() => ({ showWorkspace: show })),
        }),
        {
            name: "run-detail-ui-preferences-v2",
            storage: createJSONStorage(() => window.localStorage),
        },
    ),
);

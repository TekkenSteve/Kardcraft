"use client";

import { useSearchParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, useTransition } from "react";
import { useDispatch, useSelector } from "react-redux";
import { RootState } from "@/lib/store";
import { RunMessage, CardData } from "@/lib/features/runSlice";
import { RunEvent } from "@/lib/kardcraft/types";
import { useRunStream } from "@/lib/kardcraft/stream";
import { resetRun, setSelectedAgent, setResearchStrategy } from "@/lib/features/runSlice";
import { useSessionData } from "./use-session-data";
import { useSessionLoader } from "./use-session-loader";
import { useStreaming } from "./use-streaming";
import { useTimeline, TimelineDisplayEvent } from "./use-timeline";
import { useScrollSync } from "./use-scroll-sync";
import { useTaskControls } from "./use-task-controls";
import { useSessionTransition } from "./use-session-transition";
import { SessionDataBundle, SessionHistoryData } from "../run-detail-types";

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
    handleTaskCreated: (newTaskId: string, query: string, workflowId?: string, newSessionId?: string) => void;
    handlePause: () => void;
    handleResume: () => void;
    handleCancel: () => void;
    scrollToMessage: (messageId: string) => void;
    setSelectedAgentValue: (agent: "normal" | "card_template") => void;
    setResearchStrategyValue: (strategy: "quick" | "standard" | "deep" | "academic") => void;
    isPending: boolean;
    startTransition: (cb: () => void) => void;
}

export function useRunDetailState(): RunDetailState {
    const searchParams = useSearchParams();
    const sessionId = searchParams.get("session_id");
    const workflowIdParam = searchParams.get("workflow_id");
    const baseIsNewSession = (sessionId === "new" || !sessionId) && !workflowIdParam;

    const [actualSessionId, setActualSessionId] = useState<string | null>(null);
    const prevSessionIdParamRef = useRef<string | null>(null);
    const isNewSession = baseIsNewSession && !actualSessionId;
    const [isLoading, setIsLoading] = useState(!baseIsNewSession);
    const [error, setError] = useState<string | null>(null);
    const [sessionData, setSessionData] = useState<SessionDataBundle | null>(null);
    const [sessionHistory, setSessionHistory] = useState<SessionHistoryData>(null);
    const [currentTaskId, setCurrentTaskId] = useState<string | null>(null);
    const resolvedSessionId = actualSessionId || (sessionId && sessionId !== "new" ? sessionId : null);
    const [workspacePhase, setWorkspacePhase] = useState<"idle" | "clearing" | "loading" | "hydrated" | "empty" | "error">(
        isNewSession ? "idle" : "loading"
    );
    const [loadPhase, setLoadPhase] = useState<"idle" | "clearing" | "loading" | "hydrated" | "streaming">(
        baseIsNewSession ? "idle" : "loading"
    );
    const [activeTab, setActiveTab] = useState("conversation");
    const [isTimelineOpen, setIsTimelineOpen] = useState(false);
    const [showWorkspace, setShowWorkspace] = useState(true);
    const [workspaceExpanded, setWorkspaceExpanded] = useState(false);
    const [streamRestartKey, setStreamRestartKey] = useState(0);
    const [isPending, startTransition] = useTransition();

    const timelineStorageKey = useMemo(() => {
        if (!sessionId || sessionId === "new") return null;
        return `run-detail:timeline-open:${sessionId}`;
    }, [sessionId]);

    const workspaceExpandStorageKey = useMemo(() => {
        if (!sessionId || sessionId === "new") return null;
        return `run-detail:workspace-expanded:${sessionId}`;
    }, [sessionId]);

    const router = useRouter();
    const dispatch = useDispatch();

    const timelineScrollRef = useRef<HTMLDivElement>(null);
    const conversationScrollRef = useRef<HTMLDivElement>(null);
    const userHasScrolledRef = useRef(false);

    const hasInitializedTaskRef = useRef<string | null>(null);

    useEffect(() => {
        if (sessionId === prevSessionIdParamRef.current) return;

        // Navigating to a new session explicitly should not reuse prior actualSessionId.
        if (sessionId === "new") {
            setActualSessionId(null);
        }

        prevSessionIdParamRef.current = sessionId;
    }, [sessionId]);

    const runEvents = useSelector((state: RootState) => state.run.events);
    const runMessages = useSelector((state: RootState) => state.run.messages);
    const runStatus = useSelector((state: RootState) => state.run.status);
    const runPhase = useSelector((state: RootState) => state.run.runPhase);
    const connectionState = useSelector((state: RootState) => state.run.connectionState);
    const streamError = useSelector((state: RootState) => state.run.streamError);
    const sessionTitle = useSelector((state: RootState) => state.run.sessionTitle);
    const selectedAgent = useSelector((state: RootState) => state.run.selectedAgent);
    const researchStrategy = useSelector((state: RootState) => state.run.researchStrategy);
    const mainWorkflowId = useSelector((state: RootState) => state.run.mainWorkflowId);
    const isPaused = useSelector((state: RootState) => state.run.isPaused);
    const pauseCheckpoint = useSelector((state: RootState) => state.run.pauseCheckpoint);
    const isCancelling = useSelector((state: RootState) => state.run.isCancelling);
    const isCancelled = useSelector((state: RootState) => state.run.isCancelled);
    const cards = useSelector((state: RootState) => state.run.cards);
    const activeWorkflowId = currentTaskId || mainWorkflowId || null;

    useEffect(() => {
        // Keep local binding aligned with global task-scoped source across URL transitions/remounts.
        if (!currentTaskId && mainWorkflowId) {
            setCurrentTaskId(mainWorkflowId);
        }
    }, [currentTaskId, mainWorkflowId]);

    useEffect(() => {
        if (!baseIsNewSession) return;
        // During a live run started from `session_id=new`, the URL->real-session
        // transition can lag behind stream startup. Never clear active run state.
        const hasActiveStreamContext =
            !!activeWorkflowId ||
            runStatus === "running" ||
            runPhase === "streaming" ||
            runMessages.length > 0 ||
            runEvents.length > 0;
        if (hasActiveStreamContext) return;
        if (
            runStatus !== "idle" ||
            runPhase !== "idle" ||
            runMessages.length > 0 ||
            runEvents.length > 0 ||
            cards.length > 0
        ) {
            dispatch(resetRun());
        }
    }, [baseIsNewSession, activeWorkflowId, runStatus, runPhase, runMessages.length, runEvents.length, cards.length, dispatch]);

    useRunStream(activeWorkflowId, streamRestartKey);
    // Run detail must remain task-scoped. Subscribing to user-scoped streams here
    // mixes unrelated workflow events into the same Redux slice and can pin UI state.

    useSessionLoader({
        sessionId,
        runStatus,
        setSessionData,
        setSessionHistory,
        setIsLoading,
        setError,
        setActualSessionId,
        setLoadPhase,
        startTransition,
    });

    useSessionTransition({
        resolvedSessionId,
        currentTaskId: activeWorkflowId,
        setSessionData,
        setSessionHistory,
        setCurrentTaskId,
        setActualSessionId,
        setError,
        setIsLoading,
        setWorkspacePhase,
        setLoadPhase,
    });

    useSessionData({
        resolvedSessionId,
        isNewSession,
        workspacePhase,
        setWorkspacePhase,
    });

    useEffect(() => {
        if (!timelineStorageKey) {
            setIsTimelineOpen(false);
            return;
        }
        if (typeof window === "undefined") return;
        const stored = window.localStorage.getItem(timelineStorageKey);
        setIsTimelineOpen(stored === "true");
    }, [timelineStorageKey]);

    useEffect(() => {
        if (!timelineStorageKey) return;
        if (typeof window === "undefined") return;
        window.localStorage.setItem(timelineStorageKey, String(isTimelineOpen));
    }, [timelineStorageKey, isTimelineOpen]);

    useEffect(() => {
        if (!workspaceExpandStorageKey) {
            setWorkspaceExpanded(false);
            return;
        }
        if (typeof window === "undefined") return;
        const stored = window.localStorage.getItem(workspaceExpandStorageKey);
        setWorkspaceExpanded(stored === "true");
    }, [workspaceExpandStorageKey]);

    useEffect(() => {
        if (!workspaceExpandStorageKey) return;
        if (typeof window === "undefined") return;
        window.localStorage.setItem(workspaceExpandStorageKey, String(workspaceExpanded));
    }, [workspaceExpandStorageKey, workspaceExpanded]);

    const {
        handleTaskCreated,
        handleFetchFinalOutputClick,
        handleRetryStream: handleRetryStreamBase,
    } = useStreaming({
        sessionId,
        workflowIdParam,
        searchParams,
        router,
        isNewSession,
        currentTaskId: activeWorkflowId,
        setCurrentTaskId,
        actualSessionId,
        setActualSessionId,
        setSessionData,
        setSessionHistory,
        setIsLoading,
        setError,
        runStatus,
        runMessages,
        runEvents,
        hasInitializedTaskRef,
        startTransition,
        setLoadPhase,
    });

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
        handlePause,
        handleResume,
        handleCancel,
    } = useTaskControls({
        currentSessionId: resolvedSessionId,
        runStatus,
        isPaused,
        isCancelling,
    });

    const handleRetryStream = () => {
        handleRetryStreamBase();
        setStreamRestartKey((key) => key + 1);
    };

    const setSelectedAgentValue = (agent: "normal" | "card_template") => {
        dispatch(setSelectedAgent(agent));
    };

    const setResearchStrategyValue = (strategy: "quick" | "standard" | "deep" | "academic") => {
        dispatch(setResearchStrategy(strategy));
    };

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
        connectionState,
        streamError,
        sessionTitle,
        selectedAgent,
        researchStrategy,
        isPaused,
        pauseCheckpoint,
        isPauseLoading,
        isResumeLoading,
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

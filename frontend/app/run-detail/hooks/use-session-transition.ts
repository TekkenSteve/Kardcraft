"use client";

import { useEffect, useRef } from "react";
import { useDispatch, useSelector } from "react-redux";
import { usePathname } from "next/navigation";
import { resetRun, setCards, setRunPhase } from "@/lib/features/runSlice";
import { SessionDataBundle, SessionHistoryData } from "../run-detail-types";
import { logEvent } from "@/lib/observability/client";
import { RootState } from "@/lib/store";

export function useSessionTransition({
    resolvedSessionId,
    currentTaskId,
    setSessionData,
    setSessionHistory,
    setCurrentTaskId,
    setActualSessionId,
    setError,
    setIsLoading,
    setWorkspacePhase,
    setLoadPhase,
}: {
    resolvedSessionId: string | null;
    currentTaskId: string | null;
    setSessionData: (data: SessionDataBundle | null) => void;
    setSessionHistory: (data: SessionHistoryData) => void;
    setCurrentTaskId: (id: string | null) => void;
    setActualSessionId: (id: string | null) => void;
    setError: (value: string | null) => void;
    setIsLoading: (value: boolean) => void;
    setWorkspacePhase: (value: "idle" | "clearing" | "loading" | "hydrated" | "empty" | "error") => void;
    setLoadPhase: (value: "idle" | "clearing" | "loading" | "hydrated" | "streaming") => void;
}) {
    const dispatch = useDispatch();
    const prevResolvedRef = useRef<string | null>(null);
    const hasInitializedRef = useRef(false);
    const pathname = usePathname();
    const userId = useSelector((state: RootState) => state.auth.userId);

    useEffect(() => {
        if (resolvedSessionId === prevResolvedRef.current && hasInitializedRef.current) return;

        logEvent("session_switch", {
            from: prevResolvedRef.current,
            to: resolvedSessionId,
            userId,
            route: pathname,
        });

        const isNewToReal = !prevResolvedRef.current && !!resolvedSessionId;
        const shouldPreserveStreamingContext =
            isNewToReal &&
            !!currentTaskId;

        dispatch(setRunPhase({ next: resolvedSessionId ? "clearing" : "idle" }));
        prevResolvedRef.current = resolvedSessionId;
        hasInitializedRef.current = true;

        if (shouldPreserveStreamingContext) {
            // Preserve active task stream when session id transitions from new -> real.
            // Otherwise we drop currentTaskId and stop SSE mid-run, causing stale "started" UI.
            setWorkspacePhase("clearing");
            setLoadPhase("streaming");
            return;
        }

        dispatch(resetRun());
        dispatch(setCards([]));
        setSessionData(null);
        setSessionHistory(null);
        setCurrentTaskId(null);
        setError(null);
        setIsLoading(false);

        if (!resolvedSessionId) {
            setActualSessionId(null);
            setWorkspacePhase("idle");
            setLoadPhase("idle");
            dispatch(setRunPhase({ next: "idle" }));
            return;
        }

        setWorkspacePhase("clearing");
        setLoadPhase("clearing");
        dispatch(setRunPhase({ next: "clearing" }));
    }, [
        resolvedSessionId,
        dispatch,
        setSessionData,
        setSessionHistory,
        setCurrentTaskId,
        setActualSessionId,
        currentTaskId,
        setError,
        setIsLoading,
        setWorkspacePhase,
        setLoadPhase,
        pathname,
        userId,
    ]);
}

"use client";

import { useEffect, useRef } from "react";
import useSWR from "swr";
import { useDispatch, useSelector } from "react-redux";
import { usePathname } from "next/navigation";
import { getSessionWorkspace } from "@/lib/kardcraft/session-repository";
import { setCards } from "@/lib/features/runSlice";
import { logEvent } from "@/lib/observability/client";
import { RootState } from "@/lib/store";
import { SessionWorkspaceResponseRecord } from "@/lib/kardcraft/session-schemas";
import { inferWorkspacePhase } from "../run-detail-utils";

export function useSessionData({
    resolvedSessionId,
    isNewSession,
    workspacePhase,
    setWorkspacePhase,
}: {
    resolvedSessionId: string | null;
    isNewSession: boolean;
    workspacePhase: "idle" | "clearing" | "loading" | "hydrated" | "empty" | "error";
    setWorkspacePhase: (value: "idle" | "clearing" | "loading" | "hydrated" | "empty" | "error") => void;
}) {
    const dispatch = useDispatch();
    const pathname = usePathname();
    const userId = useSelector((state: RootState) => state.auth.userId);
    const runStatus = useSelector((state: RootState) => state.run.status);
    const prevRunStatusRef = useRef<typeof runStatus>("idle");
    const lastWorkspaceVersionRef = useRef<number | null>(null);
    const lastWorkspaceSessionRef = useRef<string | null>(null);
    const lastWorkspaceCardCountRef = useRef<number>(0);
    const cardsSessionId = resolvedSessionId;
    const { data: swrCards, isLoading, isValidating, error, mutate } = useSWR<SessionWorkspaceResponseRecord>(
        cardsSessionId ? ["session-workspace", cardsSessionId] : null,
        () => getSessionWorkspace(cardsSessionId as string),
        {
            dedupingInterval: 10_000,
            keepPreviousData: false,
            revalidateOnFocus: false,
            // Workspace hydration is event-driven by stream/card updates.
            // Avoid polling during running to prevent control-plane contention.
            refreshInterval: 0,
        }
    );

    useEffect(() => {
        if (!cardsSessionId) return;
        if (lastWorkspaceSessionRef.current !== cardsSessionId) {
            lastWorkspaceSessionRef.current = cardsSessionId;
            lastWorkspaceVersionRef.current = null;
            lastWorkspaceCardCountRef.current = 0;
        }
        const prev = prevRunStatusRef.current;
        prevRunStatusRef.current = runStatus;

        if (runStatus === "completed" && prev !== "completed") {
            void mutate();
            const retryTimers = [1200, 2800].map((delay) =>
                window.setTimeout(() => {
                    void mutate();
                }, delay)
            );
            return () => retryTimers.forEach(window.clearTimeout);
        }
    }, [cardsSessionId, runStatus, mutate]);

    useEffect(() => {
        if (isNewSession) {
            setWorkspacePhase("idle");
            return;
        }

        if (!cardsSessionId) return;

        if (error) {
            setWorkspacePhase("error");
            return;
        }

        if (isLoading || isValidating) {
            if (workspacePhase === "clearing" || workspacePhase === "idle") {
                setWorkspacePhase("loading");
            }
        }

        if (!swrCards) return;

        const responseSessionId = swrCards?.session_id;
        if (responseSessionId && responseSessionId !== cardsSessionId) return;

        const normalizedCards = Array.isArray(swrCards?.cards) ? swrCards.cards : [];
        const nextVersion = typeof swrCards?.version === "number" ? swrCards.version : null;
        const shouldUpdateCards =
            nextVersion === null ||
            lastWorkspaceVersionRef.current === null ||
            nextVersion !== lastWorkspaceVersionRef.current ||
            normalizedCards.length !== lastWorkspaceCardCountRef.current;

        if (shouldUpdateCards) {
            dispatch(setCards(normalizedCards));
            if (nextVersion !== null) {
                lastWorkspaceVersionRef.current = nextVersion;
            }
            lastWorkspaceCardCountRef.current = normalizedCards.length;
        }
        const nextPhase = inferWorkspacePhase({
            projectionStatus: swrCards?.projection_status,
            cardCount: normalizedCards.length,
        });
        if (workspacePhase !== nextPhase) {
            setWorkspacePhase(nextPhase);
        }
        logEvent("workspace_hydrated", {
            sessionId: cardsSessionId,
            cardCount: normalizedCards.length,
            userId,
            route: pathname,
        });
    }, [
        cardsSessionId,
        swrCards,
        isNewSession,
        isLoading,
        isValidating,
        error,
        workspacePhase,
        dispatch,
        setWorkspacePhase,
        pathname,
        userId,
    ]);
}

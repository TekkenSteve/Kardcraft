"use client";

import { useEffect, useRef } from "react";
import useSWR from "swr";
import { useDispatch, useSelector } from "react-redux";
import { usePathname } from "next/navigation";
import { getSessionWorkspace } from "@/lib/kardcraft/session-repository";
import { setCards, setTemplatePreflight } from "@/lib/features/runSlice";
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
    const selectedAgent = useSelector((state: RootState) => state.run.selectedAgent);
    const templatePreflight = useSelector((state: RootState) => state.run.templatePreflight);
    const prevRunStatusRef = useRef<typeof runStatus>("idle");
    const lastWorkspaceVersionRef = useRef<number | null>(null);
    const lastWorkspaceSessionRef = useRef<string | null>(null);
    const lastWorkspaceCardCountRef = useRef<number>(0);
    const completionRetryTokenRef = useRef<number>(0);
    const cardsSessionId = resolvedSessionId;
    const { data: swrCards, isLoading, isValidating, error, mutate } = useSWR<SessionWorkspaceResponseRecord>(
        cardsSessionId ? ["session-workspace", cardsSessionId] : null,
        () => getSessionWorkspace(cardsSessionId as string),
        {
            dedupingInterval: 10_000,
            keepPreviousData: false,
            revalidateOnFocus: false,
            // Keep workspace responsive while cards are being generated.
            refreshInterval: (latestData) => {
                if (!cardsSessionId) return 0;
                if (runStatus === "running") return 1500;
                if (runStatus === "completed") {
                    const cards = Array.isArray(latestData?.cards) ? latestData.cards : [];
                    const hydrated = latestData?.projection_status === "hydrated" || cards.length > 0;
                    return hydrated ? 0 : 1500;
                }
                return 0;
            },
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
            completionRetryTokenRef.current += 1;
            const retryToken = completionRetryTokenRef.current;
            const retryTimers: number[] = [];
            const completionDelays = selectedAgent === "card_template"
                ? [0, 800, 1600, 3200, 6400, 10000]
                : [0, 1200];

            const scheduleAttempt = (attempt: number) => {
                if (attempt >= completionDelays.length) return;
                const timer = window.setTimeout(async () => {
                    if (completionRetryTokenRef.current !== retryToken) return;
                    const result = await mutate();
                    const cards = Array.isArray(result?.cards) ? result.cards : [];
                    const projectionStatus = result?.projection_status;
                    const hydrated = projectionStatus === "hydrated" || cards.length > 0;
                    if (!hydrated) {
                        scheduleAttempt(attempt + 1);
                    }
                }, completionDelays[attempt]);
                retryTimers.push(timer);
            };

            scheduleAttempt(0);
            return () => retryTimers.forEach(window.clearTimeout);
        }
    }, [cardsSessionId, runStatus, mutate, selectedAgent]);

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
        const supportedQuestionTypes = Array.isArray(swrCards?.supported_question_types)
            ? swrCards.supported_question_types.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
            : [];
        if (supportedQuestionTypes.length > 0) {
            const nextTemplateId = swrCards?.template_id || templatePreflight.templateId;
            const currentQuestionTypes = templatePreflight.questionTypes || [];
            const sameLength = currentQuestionTypes.length === supportedQuestionTypes.length;
            const sameItems = sameLength && currentQuestionTypes.every((item, index) => item === supportedQuestionTypes[index]);
            if (templatePreflight.templateId !== nextTemplateId || !sameItems) {
                dispatch(setTemplatePreflight({
                    ...templatePreflight,
                    templateId: nextTemplateId,
                    questionTypes: supportedQuestionTypes,
                    checkedAt: templatePreflight.checkedAt || new Date().toISOString(),
                }));
            }
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
        templatePreflight,
    ]);
}

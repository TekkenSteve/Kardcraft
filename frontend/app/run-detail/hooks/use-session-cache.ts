"use client";

import { useCallback, useEffect } from "react";
import { resetRun, addEvent, addMessage, setCards, CardData } from "@/lib/features/runSlice";
import { RunMessage } from "@/lib/features/runSlice";
import { RunEvent } from "@/lib/kardcraft/types";
import { SessionDataBundle, SessionHistoryData } from "../run-detail-types";
import { AppDispatch } from "@/lib/store";

type SessionCacheEntry = {
    messages: RunMessage[];
    events: RunEvent[];
    cards: CardData[];
    sessionData: SessionDataBundle | null;
    sessionHistory: SessionHistoryData;
    currentTaskId: string | null;
    cachedAt: number;
};

export function useSessionCache({
    sessionId,
    actualSessionId,
    runStatus,
    setActualSessionId,
    setCurrentTaskId,
    setSessionData,
    setSessionHistory,
    setError,
    setIsLoading,
    dispatch,
    runMessages,
    runEvents,
    cards,
    sessionData,
    sessionHistory,
    currentTaskId,
    sessionCacheRef,
    shouldRefreshFromCacheRef,
    hasLoadedMessagesRef,
    hasFetchedHistoryRef,
    hasFetchedAgentTypeRef,
    hasInitializedTaskRef,
    prevSessionIdRef,
    hasInitializedRef,
    userHasScrolledRef,
    fetchSessionHistory,
}: {
    sessionId: string | null;
    actualSessionId: string | null;
    runStatus: "idle" | "running" | "completed" | "failed";
    setActualSessionId: (id: string | null) => void;
    setCurrentTaskId: (id: string | null) => void;
    setSessionData: (data: SessionDataBundle | null) => void;
    setSessionHistory: (data: SessionHistoryData) => void;
    setError: (value: string | null) => void;
    setIsLoading: (value: boolean) => void;
    dispatch: AppDispatch;
    runMessages: RunMessage[];
    runEvents: RunEvent[];
    cards: CardData[];
    sessionData: SessionDataBundle | null;
    sessionHistory: SessionHistoryData;
    currentTaskId: string | null;
    sessionCacheRef: React.MutableRefObject<Map<string, SessionCacheEntry>>;
    shouldRefreshFromCacheRef: React.MutableRefObject<string | null>;
    hasLoadedMessagesRef: React.MutableRefObject<boolean>;
    hasFetchedHistoryRef: React.MutableRefObject<boolean>;
    hasFetchedAgentTypeRef: React.MutableRefObject<string | null>;
    hasInitializedTaskRef: React.MutableRefObject<string | null>;
    prevSessionIdRef: React.MutableRefObject<string | null>;
    hasInitializedRef: React.MutableRefObject<boolean>;
    userHasScrolledRef: React.MutableRefObject<boolean>;
    fetchSessionHistory: (forceReload?: boolean, showLoading?: boolean) => void;
}) {
    const CACHE_TTL_MS = 5 * 60 * 1000;
    const MAX_CACHE_ENTRIES = 20;

    const upsertSessionCache = useCallback((sessionKey: string, payload: {
        messages: RunMessage[];
        events: RunEvent[];
        cards: CardData[];
        sessionData: SessionDataBundle | null;
        sessionHistory: SessionHistoryData;
        currentTaskId: string | null;
    }) => {
        sessionCacheRef.current.set(sessionKey, {
            ...payload,
            cachedAt: Date.now(),
        });

        if (sessionCacheRef.current.size > MAX_CACHE_ENTRIES) {
            const entries = Array.from(sessionCacheRef.current.entries())
                .sort((a, b) => a[1].cachedAt - b[1].cachedAt);
            const toRemove = entries.slice(0, sessionCacheRef.current.size - MAX_CACHE_ENTRIES);
            toRemove.forEach(([key]) => sessionCacheRef.current.delete(key));
        }
    }, [sessionCacheRef]);

    useEffect(() => {
        if (sessionId === null || sessionId === undefined) return;

        const effectiveSessionId = (sessionId && sessionId !== "new" ? sessionId : null) || actualSessionId;
        const cached = effectiveSessionId ? sessionCacheRef.current.get(effectiveSessionId) : null;
        const cacheExpired = cached ? (Date.now() - cached.cachedAt > CACHE_TTL_MS) : false;
        if (cached && cacheExpired && effectiveSessionId) {
            sessionCacheRef.current.delete(effectiveSessionId);
        }
        const usableCache = cached && !cacheExpired ? cached : null;

        const isTransitioningNewSession =
            sessionId === "new" && (!!actualSessionId || !!currentTaskId || runStatus === "running");

        if (sessionId === "new" && !isTransitioningNewSession) {
            dispatch(resetRun());
            setActualSessionId(null);
            setCurrentTaskId(null);
            setSessionData(null);
            setSessionHistory(null);
            setError(null);
            setIsLoading(false);
            dispatch(setCards([]));
        }

        const sessionChanged = sessionId !== prevSessionIdRef.current;
        const isNewToReal = prevSessionIdRef.current === "new" && sessionId && sessionId !== "new";
        const preserveNewToReal = isNewToReal && !!currentTaskId;
        const shouldResetRedux = !hasInitializedRef.current || (sessionChanged && !preserveNewToReal && !usableCache);

        if (usableCache && effectiveSessionId) {
            dispatch(resetRun());
            dispatch(setCards(usableCache.cards || []));
            usableCache.events?.forEach((event: RunEvent) => dispatch(addEvent(event)));
            usableCache.messages?.forEach((msg: RunMessage) => dispatch(addMessage(msg)));
            setSessionData(usableCache.sessionData || null);
            setSessionHistory(usableCache.sessionHistory || null);
            setCurrentTaskId(usableCache.currentTaskId || null);
            hasLoadedMessagesRef.current = true;
            hasFetchedHistoryRef.current = true;
            setIsLoading(false);
            setError(null);
            shouldRefreshFromCacheRef.current = effectiveSessionId;
        } else if (shouldResetRedux) {
            dispatch(resetRun());
            userHasScrolledRef.current = false;
        }

        if (sessionChanged || !hasInitializedRef.current) {
            if (!preserveNewToReal && sessionChanged) {
                setActualSessionId(null);
            }
            prevSessionIdRef.current = sessionId;
            hasInitializedRef.current = true;

            if (!preserveNewToReal) {
                hasLoadedMessagesRef.current = false;
                hasFetchedHistoryRef.current = false;
                hasInitializedTaskRef.current = null;
                setCurrentTaskId(null);
            }
            hasFetchedAgentTypeRef.current = null;
        }
    }, [
        sessionId,
        actualSessionId,
        runStatus,
        dispatch,
        setActualSessionId,
        setCurrentTaskId,
        setSessionData,
        setSessionHistory,
        setError,
        setIsLoading,
        sessionCacheRef,
        shouldRefreshFromCacheRef,
        hasLoadedMessagesRef,
        hasFetchedHistoryRef,
        hasFetchedAgentTypeRef,
        hasInitializedTaskRef,
        prevSessionIdRef,
        hasInitializedRef,
        userHasScrolledRef,
    ]);

    useEffect(() => {
        const effectiveSessionId = actualSessionId || (sessionId && sessionId !== "new" ? sessionId : null);
        if (!effectiveSessionId) return;
        if (shouldRefreshFromCacheRef.current !== effectiveSessionId) return;

        shouldRefreshFromCacheRef.current = null;
        fetchSessionHistory(false, false);
    }, [fetchSessionHistory, actualSessionId, sessionId, shouldRefreshFromCacheRef]);

    useEffect(() => {
        const effectiveSessionId = actualSessionId || (sessionId && sessionId !== "new" ? sessionId : null);
        if (!effectiveSessionId) return;
        if (sessionId === "new") return;

        const hasData =
            (runMessages && runMessages.length > 0) ||
            (runEvents && runEvents.length > 0) ||
            (cards && cards.length > 0) ||
            !!sessionData ||
            !!sessionHistory;

        if (!hasData) return;

        upsertSessionCache(effectiveSessionId, {
            messages: runMessages || [],
            events: runEvents || [],
            cards: cards || [],
            sessionData,
            sessionHistory,
            currentTaskId,
        });
    }, [
        actualSessionId,
        sessionId,
        runMessages,
        runEvents,
        cards,
        sessionData,
        sessionHistory,
        currentTaskId,
        upsertSessionCache,
    ]);
}

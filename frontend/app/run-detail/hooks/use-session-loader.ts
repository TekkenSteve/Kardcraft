"use client";

import { useEffect, useMemo } from "react";
import useSWR from "swr";
import { useDispatch } from "react-redux";
import { useTranslation } from "react-i18next";
import {
    getSession,
    getSessionConversation,
    getSessionTimeline,
    getSessionHistory,
} from "@/lib/kardcraft/session-repository";
import {
    SessionRecord,
    SessionConversationResponseRecord,
    SessionTimelineResponseRecord,
    SessionHistoryResponseRecord,
    TimelineEventSchema,
    ConversationMessageSchema,
} from "@/lib/kardcraft/session-schemas";
import { SessionDataBundle, SessionHistoryData } from "../run-detail-types";
import {
    addMessage,
    addEvent,
    setSelectedAgent,
    setResearchStrategy,
} from "@/lib/features/runSlice";
type SessionBundle = {
    session: SessionRecord;
    conversation: SessionConversationResponseRecord;
    timeline: SessionTimelineResponseRecord;
    history: SessionHistoryResponseRecord;
};

const formatMessageTimestamp = (raw?: string): string => {
    if (!raw) return new Date().toLocaleTimeString();
    const parsed = Date.parse(raw);
    if (!Number.isNaN(parsed)) {
        return new Date(parsed).toLocaleTimeString();
    }
    // Keep pre-formatted time strings as-is (for legacy records).
    return raw;
};

export function useSessionLoader({
    sessionId,
    runStatus,
    setSessionData,
    setSessionHistory,
    setActualSessionId,
    setIsLoading,
    setError,
    setLoadPhase,
    startTransition,
}: {
    sessionId: string | null;
    runStatus: "idle" | "running" | "completed" | "failed";
    setSessionData: (data: SessionDataBundle | null) => void;
    setSessionHistory: (data: SessionHistoryData) => void;
    setActualSessionId: (id: string | null) => void;
    setIsLoading: (value: boolean) => void;
    setError: (value: string | null) => void;
    setLoadPhase: (value: "idle" | "clearing" | "loading" | "hydrated" | "streaming") => void;
    startTransition: (cb: () => void) => void;
}) {
    const dispatch = useDispatch();
    const { t } = useTranslation();

    const shouldLoad = !!sessionId && sessionId !== "new";
    const swrKey = shouldLoad ? ["session-bundle", sessionId] : null;

    const fetcher = useMemo(() => {
        if (!sessionId || sessionId === "new") return null;
        return async (): Promise<SessionBundle> => {
            const [session, conversation, timeline, history] = await Promise.all([
                getSession(sessionId),
                getSessionConversation(sessionId),
                getSessionTimeline(sessionId, 500, 0, true),
                getSessionHistory(sessionId),
            ]);
            return { session, conversation, timeline, history };
        };
    }, [sessionId]);

    const { data, error, isLoading } = useSWR<SessionBundle>(swrKey, fetcher || undefined, {
        keepPreviousData: false,
        revalidateOnFocus: false,
        dedupingInterval: 10_000,
    });

    useEffect(() => {
        if (!sessionId || sessionId === "new") {
            return;
        }

        const shouldDriveLoadingUI = runStatus !== "running";
        if (shouldDriveLoadingUI) {
            setIsLoading(isLoading);
        }
        if (isLoading && shouldDriveLoadingUI) {
            setLoadPhase("loading");
        }
        if (error) {
            setError(error instanceof Error ? error.message : t("runDetail.sessionLoadFailed"));
            return;
        }

        if (!data) return;

        setActualSessionId(sessionId);
        setError(null);

        const { session, conversation, timeline, history } = data;

        if (session) {
            const isTemplateSession =
                session.first_task_mode === "card_template" ||
                session.is_research_session === true;
            const strategy = session.research_strategy || "standard";
            dispatch(setSelectedAgent(isTemplateSession ? "card_template" : "normal"));
            if (isTemplateSession) {
                dispatch(setResearchStrategy(strategy as "quick" | "standard" | "deep" | "academic"));
            }
        }

        startTransition(() => {
            setSessionHistory(history);
        });
        startTransition(() => {
            setSessionData({ conversation, timeline });
        });

        const timelineEvents = timeline?.events || [];
        timelineEvents.forEach((event) => {
            const safeEvent = TimelineEventSchema.safeParse(event);
            if (safeEvent.success) {
                dispatch(addEvent({ ...safeEvent.data, isHistorical: true }));
            }
        });

        const messages = conversation?.messages || [];
        messages.forEach((msg, index: number) => {
            const safeMessage = ConversationMessageSchema.safeParse(msg);
            if (!safeMessage.success) return;
            const timestamp = formatMessageTimestamp(safeMessage.data.timestamp);
            dispatch(addMessage({
                id: safeMessage.data.id || `${safeMessage.data.role}-${index}`,
                role: safeMessage.data.role || "assistant",
                content: safeMessage.data.content || "",
                timestamp,
                taskId: safeMessage.data.task_id,
                metadata: safeMessage.data.metadata,
                isError: safeMessage.data.role === "system" && /failed/i.test(safeMessage.data.content || ""),
            }));
        });

        if (shouldDriveLoadingUI) {
            setIsLoading(false);
            setLoadPhase("hydrated");
        }
    }, [
        sessionId,
        data,
        error,
        isLoading,
        dispatch,
        setSessionData,
        setSessionHistory,
        setActualSessionId,
        setIsLoading,
        setError,
        setLoadPhase,
        startTransition,
        runStatus,
        t,
    ]);
}

"use client";

import { useEffect, useState } from "react";
import { useDispatch } from "react-redux";
import { useTranslation } from "react-i18next";
import {
    cancelSessionTask,
    getSessionState,
    pauseSessionTask,
    resumeSessionTask,
    SessionStateResponse,
} from "@/lib/kardcraft/api";
import { setPaused, setCancelled, setCancelling, setStreamError } from "@/lib/features/runSlice";

export function useTaskControls({
    currentSessionId,
    runStatus,
    isPaused,
    isCancelling,
}: {
    currentSessionId: string | null;
    runStatus: "idle" | "running" | "completed" | "failed";
    isPaused: boolean;
    isCancelling: boolean;
}) {
    const dispatch = useDispatch();
    const { t } = useTranslation();
    const [isPauseLoading, setIsPauseLoading] = useState(false);
    const [isResumeLoading, setIsResumeLoading] = useState(false);

    const sessionPaused = (state: SessionStateResponse) =>
        state.session_control_state === "ACTIVE_PAUSED" || state.task_state === "PAUSED" || state.status === "paused";

    const sessionCancelled = (state: SessionStateResponse) =>
        state.task_state === "CANCELED" || state.status === "cancelled";

    useEffect(() => {
        if (currentSessionId && runStatus === "running") {
            getSessionState(currentSessionId)
                .then(state => {
                    dispatch(setPaused({
                        paused: sessionPaused(state),
                        reason: undefined,
                    }));
                    if (sessionCancelled(state)) {
                        dispatch(setCancelled({ value: true, message: t("runDetail.cancelledMessage") }));
                    }
                })
                .catch(err => {
                    console.warn("[RunDetail] Failed to fetch session-state:", err);
                });
        }
    }, [currentSessionId, runStatus, dispatch, t]);

    useEffect(() => {
        if (!isPaused || !currentSessionId) return;

        const REFRESH_INTERVAL_MS = 20000;

        const refreshControlState = async () => {
            try {
                const state = await getSessionState(currentSessionId);
                if (!sessionPaused(state)) {
                    dispatch(setPaused({ paused: false }));
                }
                if (sessionCancelled(state)) {
                    dispatch(setCancelled({ value: true, message: t("runDetail.cancelledMessage") }));
                }
            } catch (err) {
                console.warn("[RunDetail] Failed to refresh session-state:", err);
            }
        };

        const interval = setInterval(refreshControlState, REFRESH_INTERVAL_MS);
        return () => clearInterval(interval);
    }, [isPaused, currentSessionId, dispatch, t]);

    useEffect(() => {
        if (!isCancelling || !currentSessionId) return;

        const CANCEL_POLL_INTERVAL_MS = 2000;

        const checkCancelledState = async () => {
            try {
                const state = await getSessionState(currentSessionId);
                if (sessionCancelled(state)) {
                    dispatch(setCancelled({ value: true, message: t("runDetail.cancelledMessage") }));
                }
            } catch (err) {
                console.warn("[RunDetail] Failed to check cancelled session state:", err);
            }
        };

        checkCancelledState();
        const interval = setInterval(checkCancelledState, CANCEL_POLL_INTERVAL_MS);
        return () => clearInterval(interval);
    }, [isCancelling, currentSessionId, dispatch, t]);

    useEffect(() => {
        if (isPaused) {
            setIsPauseLoading(false);
            setIsResumeLoading(false);
        } else {
            setIsResumeLoading(false);
            setIsPauseLoading(false);
        }
    }, [isPaused]);

    const handlePause = async () => {
        if (!currentSessionId) {
            dispatch(setStreamError(t("runDetail.pauseFailed")));
            return;
        }
        setIsPauseLoading(true);
        try {
            await pauseSessionTask(currentSessionId);
        } catch (err) {
            setIsPauseLoading(false);
            dispatch(setStreamError(err instanceof Error ? err.message : t("runDetail.pauseFailed")));
        }
    };

    const handleResume = async () => {
        if (!currentSessionId) {
            dispatch(setStreamError(t("runDetail.resumeFailed")));
            return;
        }
        setIsResumeLoading(true);
        try {
            await resumeSessionTask(currentSessionId);
        } catch (err) {
            setIsResumeLoading(false);
            dispatch(setStreamError(err instanceof Error ? err.message : t("runDetail.resumeFailed")));
        }
    };

    const handleCancel = async () => {
        if (!currentSessionId) {
            dispatch(setStreamError(t("runDetail.cancelFailed")));
            return;
        }
        dispatch(setCancelling({ value: true, message: t("runDetail.cancellingStatus") }));
        try {
            await cancelSessionTask(currentSessionId);
        } catch (err) {
            dispatch(setCancelling({ value: false }));
            dispatch(setStreamError(err instanceof Error ? err.message : t("runDetail.cancelFailed")));
        }
    };

    return {
        isPauseLoading,
        isResumeLoading,
        handlePause,
        handleResume,
        handleCancel,
    };
}

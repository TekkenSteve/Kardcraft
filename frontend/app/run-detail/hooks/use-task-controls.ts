"use client";

import { useEffect, useState } from "react";
import { useDispatch } from "react-redux";
import { useTranslation } from "react-i18next";
import {
    cancelTask,
    getTask,
    getTaskControlState,
    pauseTask,
    resumeTask,
} from "@/lib/kardcraft/api";
import { setPaused, setCancelled, setCancelling, setStatus, setStreamError } from "@/lib/features/runSlice";

export function useTaskControls({
    currentTaskId,
    runStatus,
    isPaused,
    isCancelling,
}: {
    currentTaskId: string | null;
    runStatus: "idle" | "running" | "completed" | "failed";
    isPaused: boolean;
    isCancelling: boolean;
}) {
    const dispatch = useDispatch();
    const { t } = useTranslation();
    const [isPauseLoading, setIsPauseLoading] = useState(false);
    const [isResumeLoading, setIsResumeLoading] = useState(false);
    const [isPauseSyncing, setIsPauseSyncing] = useState(false);
    const [canControlTask, setCanControlTask] = useState(false);

    const taskPaused = (state: { is_paused: boolean }) => state.is_paused;

    const taskCancelled = (state: { is_cancelled: boolean }) => state.is_cancelled;
    const isTerminalTaskStatus = (status: unknown) => {
        const normalized = String(status || "").toUpperCase();
        return normalized === "TASK_STATUS_COMPLETED" || normalized === "TASK_STATUS_FAILED" || normalized === "TASK_STATUS_CANCELLED";
    };
    const syncTaskTerminalStatus = async () => {
        if (!currentTaskId) return;
        const task = await getTask(currentTaskId);
        if (!isTerminalTaskStatus(task?.status)) {
            setCanControlTask(true);
            return;
        }
        setCanControlTask(false);
        if (String(task?.status).toUpperCase() === "TASK_STATUS_COMPLETED") {
            dispatch(setStatus("completed"));
            return;
        }
        if (String(task?.status).toUpperCase() === "TASK_STATUS_CANCELLED") {
            dispatch(setCancelled({ value: true, message: t("runDetail.cancelledMessage") }));
            return;
        }
        dispatch(setStatus("failed"));
    };

    useEffect(() => {
        setCanControlTask(!!currentTaskId && runStatus === "running");
    }, [currentTaskId, runStatus]);

    useEffect(() => {
        if (currentTaskId && runStatus === "running") {
            getTaskControlState(currentTaskId)
                .then(state => {
                    dispatch(setPaused({
                        paused: taskPaused(state),
                        reason: undefined,
                    }));
                    if (taskCancelled(state)) {
                        dispatch(setCancelled({ value: true, message: t("runDetail.cancelledMessage") }));
                    }
                })
                .catch(err => {
                    console.warn("[RunDetail] Failed to fetch task control-state:", err);
                });
            syncTaskTerminalStatus().catch((err) => {
                console.warn("[RunDetail] Failed to sync task terminal status:", err);
            });
        }
    }, [currentTaskId, runStatus, dispatch, t]);

    useEffect(() => {
        if (!currentTaskId || runStatus !== "running") return;
        const timer = setInterval(() => {
            syncTaskTerminalStatus().catch((err) => {
                console.warn("[RunDetail] Failed to poll task terminal status:", err);
            });
        }, 2500);
        return () => clearInterval(timer);
    }, [currentTaskId, runStatus]);

    useEffect(() => {
        if ((!isPaused && !isPauseSyncing) || !currentTaskId) return;

        const REFRESH_INTERVAL_MS = 1500;

        const refreshControlState = async () => {
            try {
                const state = await getTaskControlState(currentTaskId);
                const paused = taskPaused(state);
                dispatch(setPaused({ paused }));
                if (paused) {
                    setIsPauseLoading(false);
                    setIsResumeLoading(false);
                }
                if (!paused && isPauseSyncing) {
                    setIsPauseSyncing(false);
                    setIsPauseLoading(false);
                    setIsResumeLoading(false);
                }
                if (taskCancelled(state)) {
                    setIsPauseSyncing(false);
                    setIsPauseLoading(false);
                    setIsResumeLoading(false);
                    dispatch(setCancelled({ value: true, message: t("runDetail.cancelledMessage") }));
                }
            } catch (err) {
                console.warn("[RunDetail] Failed to refresh task control-state:", err);
            }
        };

        refreshControlState();
        const interval = setInterval(refreshControlState, REFRESH_INTERVAL_MS);
        return () => clearInterval(interval);
    }, [isPaused, isPauseSyncing, currentTaskId, dispatch, t]);

    useEffect(() => {
        if (!isCancelling || !currentTaskId) return;

        const CANCEL_POLL_INTERVAL_MS = 2000;

        const checkCancelledState = async () => {
            try {
                const state = await getTaskControlState(currentTaskId);
                if (taskCancelled(state)) {
                    dispatch(setCancelled({ value: true, message: t("runDetail.cancelledMessage") }));
                }
            } catch (err) {
                console.warn("[RunDetail] Failed to check cancelled task state:", err);
            }
        };

        checkCancelledState();
        const interval = setInterval(checkCancelledState, CANCEL_POLL_INTERVAL_MS);
        return () => clearInterval(interval);
    }, [isCancelling, currentTaskId, dispatch, t]);

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
        if (!currentTaskId || !canControlTask) {
            dispatch(setStreamError(t("runDetail.pauseFailed")));
            return;
        }
        setIsPauseLoading(true);
        try {
            await pauseTask(currentTaskId);
            setIsPauseSyncing(true);
        } catch (err) {
            setIsPauseSyncing(false);
            setIsPauseLoading(false);
            if (err instanceof Error && err.message.includes("invalid-transition")) {
                setCanControlTask(false);
            }
            dispatch(setStreamError(err instanceof Error ? err.message : t("runDetail.pauseFailed")));
        }
    };

    const handleResume = async () => {
        if (!currentTaskId || !canControlTask) {
            dispatch(setStreamError(t("runDetail.resumeFailed")));
            return;
        }
        setIsResumeLoading(true);
        try {
            await resumeTask(currentTaskId);
            setIsPauseSyncing(true);
        } catch (err) {
            setIsPauseSyncing(false);
            setIsResumeLoading(false);
            if (err instanceof Error && err.message.includes("invalid-transition")) {
                setCanControlTask(false);
            }
            dispatch(setStreamError(err instanceof Error ? err.message : t("runDetail.resumeFailed")));
        }
    };

    const handleCancel = async () => {
        if (!currentTaskId || !canControlTask) {
            dispatch(setStreamError(t("runDetail.cancelFailed")));
            return;
        }
        dispatch(setCancelling({ value: true, message: t("runDetail.cancellingStatus") }));
        try {
            await cancelTask(currentTaskId);
        } catch (err) {
            dispatch(setCancelling({ value: false }));
            if (err instanceof Error && (err.message.includes("invalid-transition") || err.message.includes("task-not-found"))) {
                setCanControlTask(false);
            }
            dispatch(setStreamError(err instanceof Error ? err.message : t("runDetail.cancelFailed")));
        }
    };

    return {
        isPauseLoading,
        isResumeLoading,
        canControlTask,
        handlePause,
        handleResume,
        handleCancel,
    };
}

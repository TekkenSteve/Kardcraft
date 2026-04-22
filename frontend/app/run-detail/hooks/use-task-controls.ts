"use client";

import { useCallback, useEffect } from "react";
import { useActorRef, useSelector } from "@xstate/react";
import { useTranslation } from "react-i18next";
import {
    ApiError,
    cancelTask,
    getTask,
    getTaskControlState,
    pauseTask,
    resumeTask,
} from "@/lib/kardcraft/api";
import { taskControlMachine } from "@/lib/run/task-control-machine";
import { useRunCommands } from "@/lib/run/system";

const TERMINAL_POLL_INTERVAL_MS = 2500;
const CONTROL_POLL_INTERVAL_MS = 1500;

const isControlTransitionError = (err: unknown): boolean => {
    if (!(err instanceof ApiError)) return false;
    return err.code === "invalid-transition";
};

const isControlTaskMissingError = (err: unknown): boolean => {
    if (!(err instanceof ApiError)) return false;
    return err.code === "task-not-found";
};

export function useTaskControls({
    sessionId,
    currentTaskId,
    runStatus,
    isPaused,
    isCancelling,
}: {
    sessionId: string | null;
    currentTaskId: string | null;
    runStatus: "idle" | "running" | "completed" | "failed";
    isPaused: boolean;
    isCancelling: boolean;
}) {
    const commands = useRunCommands();
    const { t } = useTranslation();

    const actor = useActorRef(taskControlMachine);

    useEffect(() => {
        actor.send({
            type: "SYNC_INPUT",
            currentTaskId,
            runStatus,
            isCancelling,
        });
    }, [actor, currentTaskId, isCancelling, runStatus]);

    const isPauseLoading = useSelector(actor, (snapshot) => snapshot.context.isPauseLoading);
    const isResumeLoading = useSelector(actor, (snapshot) => snapshot.context.isResumeLoading);
    const isPauseSyncing = useSelector(actor, (snapshot) => snapshot.context.isPauseSyncing);
    const canControlTask = useSelector(actor, (snapshot) => snapshot.context.canControlTask);

    const syncTaskTerminalStatus = useCallback(async () => {
        if (!currentTaskId) return;
        const task = await getTask(currentTaskId);
        if (task.status === "running" || task.status === "queued") return;

        actor.send({
            type: "TERMINAL_STATUS_DETECTED",
            status: task.status,
        });

        if (task.status === "completed") {
            commands.setStatus(sessionId, "completed");
            return;
        }
        if (task.status === "cancelled") {
            commands.setCancelled(sessionId, true);
            return;
        }
        commands.setStatus(sessionId, "failed");
    }, [actor, commands, currentTaskId, sessionId]);

    const refreshControlState = useCallback(async () => {
        if (!currentTaskId) return;
        const state = await getTaskControlState(currentTaskId);
        actor.send({
            type: "CONTROL_STATE_UPDATED",
            paused: state.is_paused,
            cancelled: state.is_cancelled,
        });
        commands.setPaused(sessionId, state.is_paused, null, undefined);
        if (state.is_cancelled) {
            commands.setCancelled(sessionId, true);
        }
    }, [actor, commands, currentTaskId, sessionId]);

    useEffect(() => {
        if (!currentTaskId || runStatus !== "running") return;
        const run = () => {
            syncTaskTerminalStatus().catch((err) => {
                console.warn("[RunDetail] Failed to poll task terminal status:", err);
            });
        };
        run();
        const timer = setInterval(run, TERMINAL_POLL_INTERVAL_MS);
        return () => clearInterval(timer);
    }, [currentTaskId, runStatus, syncTaskTerminalStatus]);

    useEffect(() => {
        if (!currentTaskId || runStatus !== "running") return;
        if (!isPaused && !isPauseSyncing && !isCancelling) return;

        const run = () => {
            refreshControlState().catch((err) => {
                console.warn("[RunDetail] Failed to refresh task control-state:", err);
            });
        };
        run();
        const timer = setInterval(run, CONTROL_POLL_INTERVAL_MS);
        return () => clearInterval(timer);
    }, [currentTaskId, isCancelling, isPauseSyncing, isPaused, refreshControlState, runStatus]);

    const handlePause = async () => {
        if (!currentTaskId || !canControlTask) {
            commands.setStreamError(sessionId, t("runDetail.pauseFailed"));
            return;
        }
        actor.send({ type: "PAUSE_REQUESTED" });
        try {
            await pauseTask(currentTaskId);
            actor.send({ type: "CONTROL_SYNC_STARTED" });
        } catch (err) {
            actor.send({
                type: "CONTROL_REQUEST_FAILED",
                blockCurrentTask: isControlTransitionError(err),
            });
            commands.setStreamError(sessionId, err instanceof Error ? err.message : t("runDetail.pauseFailed"));
        }
    };

    const handleResume = async () => {
        if (!currentTaskId || !canControlTask) {
            commands.setStreamError(sessionId, t("runDetail.resumeFailed"));
            return;
        }
        actor.send({ type: "RESUME_REQUESTED" });
        try {
            await resumeTask(currentTaskId);
            actor.send({ type: "CONTROL_SYNC_STARTED" });
        } catch (err) {
            actor.send({
                type: "CONTROL_REQUEST_FAILED",
                blockCurrentTask: isControlTransitionError(err),
            });
            commands.setStreamError(sessionId, err instanceof Error ? err.message : t("runDetail.resumeFailed"));
        }
    };

    const handleCancel = async () => {
        if (!currentTaskId || !canControlTask) {
            commands.setStreamError(sessionId, t("runDetail.cancelFailed"));
            return;
        }
        commands.setCancelling(sessionId, true);
        try {
            await cancelTask(currentTaskId);
            actor.send({ type: "CONTROL_SYNC_STARTED" });
        } catch (err) {
            commands.setCancelling(sessionId, false);
            actor.send({
                type: "CONTROL_REQUEST_FAILED",
                blockCurrentTask: isControlTransitionError(err) || isControlTaskMissingError(err),
            });
            commands.setStreamError(sessionId, err instanceof Error ? err.message : t("runDetail.cancelFailed"));
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

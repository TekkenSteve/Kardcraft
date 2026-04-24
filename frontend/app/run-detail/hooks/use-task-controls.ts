"use client";

import { useEffect } from "react";
import { useActorRef, useSelector } from "@xstate/react";
import { useTranslation } from "react-i18next";
import {
    ApiError,
    cancelTask,
    pauseTask,
    resumeTask,
} from "@/lib/kardcraft/api";
import { taskControlMachine } from "@/lib/run/task-control-machine";
import { useRunCommands } from "@/lib/run/system";

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
    isCancelling,
    onPauseConfirmed,
    onResumeConfirmed,
    onCancelConfirmed,
}: {
    sessionId: string | null;
    currentTaskId: string | null;
    runStatus: "idle" | "running" | "pausing" | "paused" | "cancelling" | "cancelled" | "completed" | "failed";
    isCancelling: boolean;
    onPauseConfirmed?: (taskId: string) => void;
    onResumeConfirmed?: (taskId: string) => void;
    onCancelConfirmed?: (taskId: string) => void;
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
    const canControlTask = useSelector(actor, (snapshot) => snapshot.context.canControlTask);

    const handlePause = async () => {
        if (!currentTaskId || !canControlTask) {
            commands.setStreamError(sessionId, t("runDetail.pauseFailed"));
            return;
        }
        commands.upsertMessage(sessionId, {
            id: `status-control-pausing-${currentTaskId}`,
            role: "status",
            content: t("runDetail.pausingStatus"),
            timestamp: new Date().toLocaleTimeString(),
            taskId: currentTaskId,
            eventType: "workflow.pausing",
        });
        commands.setStatus(sessionId, "pausing");
        actor.send({ type: "PAUSE_REQUESTED" });
        try {
            await pauseTask(currentTaskId);
            actor.send({
                type: "CONTROL_STATE_UPDATED",
                cancelled: false,
            });
            onPauseConfirmed?.(currentTaskId);
        } catch (err) {
            commands.setStatus(sessionId, "running");
            commands.clearStatusMessages(sessionId, currentTaskId);
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
        commands.upsertMessage(sessionId, {
            id: `status-control-resuming-${currentTaskId}`,
            role: "status",
            content: t("runDetail.resumingStatus"),
            timestamp: new Date().toLocaleTimeString(),
            taskId: currentTaskId,
            eventType: "workflow.resuming",
        });
        actor.send({ type: "RESUME_REQUESTED" });
        try {
            await resumeTask(currentTaskId);
            actor.send({
                type: "CONTROL_STATE_UPDATED",
                cancelled: false,
            });
            onResumeConfirmed?.(currentTaskId);
        } catch (err) {
            commands.clearStatusMessages(sessionId, currentTaskId);
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
        commands.upsertMessage(sessionId, {
            id: `status-control-cancelling-${currentTaskId}`,
            role: "status",
            content: t("runDetail.cancellingStatus"),
            timestamp: new Date().toLocaleTimeString(),
            taskId: currentTaskId,
            eventType: "workflow.cancelling",
        });
        commands.setCancelling(sessionId, true);
        try {
            await cancelTask(currentTaskId);
            actor.send({
                type: "CONTROL_STATE_UPDATED",
                cancelled: true,
            });
            onCancelConfirmed?.(currentTaskId);
        } catch (err) {
            commands.setCancelling(sessionId, false);
            commands.clearStatusMessages(sessionId, currentTaskId);
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

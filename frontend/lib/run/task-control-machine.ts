import { assign, createMachine } from "xstate";
import { TaskStatus } from "@/lib/kardcraft/api";

type RunStatus = "idle" | "running" | "completed" | "failed";

export type TaskControlContext = {
    currentTaskId: string | null;
    runStatus: RunStatus;
    isCancelling: boolean;
    blockedTaskId: string | null;
    isPauseLoading: boolean;
    isResumeLoading: boolean;
    isPauseSyncing: boolean;
    canControlTask: boolean;
};

type SyncInputEvent = {
    type: "SYNC_INPUT";
    currentTaskId: string | null;
    runStatus: RunStatus;
    isCancelling: boolean;
};

type TaskControlEvent =
    | SyncInputEvent
    | { type: "PAUSE_REQUESTED" }
    | { type: "RESUME_REQUESTED" }
    | { type: "CONTROL_SYNC_STARTED" }
    | { type: "CONTROL_STATE_UPDATED"; paused: boolean; cancelled: boolean }
    | { type: "CONTROL_REQUEST_FAILED"; blockCurrentTask?: boolean }
    | { type: "TERMINAL_STATUS_DETECTED"; status: TaskStatus };

const isTerminalStatus = (status: TaskStatus): boolean => {
    return status === "completed" || status === "failed" || status === "cancelled";
};

const computeCanControlTask = (
    currentTaskId: string | null,
    runStatus: RunStatus,
    isCancelling: boolean,
    blockedTaskId: string | null,
): boolean => {
    if (!currentTaskId) return false;
    if (runStatus !== "running") return false;
    if (isCancelling) return false;
    return blockedTaskId !== currentTaskId;
};

export const taskControlMachine = createMachine({
    types: {} as {
        context: TaskControlContext;
        events: TaskControlEvent;
    },
    context: {
        currentTaskId: null,
        runStatus: "idle",
        isCancelling: false,
        blockedTaskId: null,
        isPauseLoading: false,
        isResumeLoading: false,
        isPauseSyncing: false,
        canControlTask: false,
    },
    on: {
        SYNC_INPUT: {
            actions: assign(({ context, event }) => {
                const blockedTaskId =
                    context.blockedTaskId && context.blockedTaskId === event.currentTaskId
                        ? context.blockedTaskId
                        : null;

                return {
                    currentTaskId: event.currentTaskId,
                    runStatus: event.runStatus,
                    isCancelling: event.isCancelling,
                    blockedTaskId,
                    canControlTask: computeCanControlTask(
                        event.currentTaskId,
                        event.runStatus,
                        event.isCancelling,
                        blockedTaskId,
                    ),
                };
            }),
        },
        PAUSE_REQUESTED: {
            actions: assign(() => ({
                isPauseLoading: true,
                isResumeLoading: false,
            })),
        },
        RESUME_REQUESTED: {
            actions: assign(() => ({
                isResumeLoading: true,
                isPauseLoading: false,
            })),
        },
        CONTROL_SYNC_STARTED: {
            actions: assign(() => ({
                isPauseSyncing: true,
            })),
        },
        CONTROL_STATE_UPDATED: {
            actions: assign(({ context, event }) => {
                const blockedTaskId = event.cancelled ? context.currentTaskId : context.blockedTaskId;
                return {
                    blockedTaskId,
                    isPauseLoading: false,
                    isResumeLoading: false,
                    isPauseSyncing: false,
                    canControlTask: computeCanControlTask(
                        context.currentTaskId,
                        context.runStatus,
                        context.isCancelling,
                        blockedTaskId,
                    ),
                };
            }),
        },
        CONTROL_REQUEST_FAILED: {
            actions: assign(({ context, event }) => {
                const blockedTaskId = event.blockCurrentTask ? context.currentTaskId : context.blockedTaskId;
                return {
                    blockedTaskId,
                    isPauseLoading: false,
                    isResumeLoading: false,
                    isPauseSyncing: false,
                    canControlTask: computeCanControlTask(
                        context.currentTaskId,
                        context.runStatus,
                        context.isCancelling,
                        blockedTaskId,
                    ),
                };
            }),
        },
        TERMINAL_STATUS_DETECTED: {
            actions: assign(({ context, event }) => {
                const blockedTaskId = isTerminalStatus(event.status) ? context.currentTaskId : context.blockedTaskId;
                return {
                    blockedTaskId,
                    canControlTask: computeCanControlTask(
                        context.currentTaskId,
                        context.runStatus,
                        context.isCancelling,
                        blockedTaskId,
                    ),
                };
            }),
        },
    },
});

import { assign, createMachine } from "xstate";

type RunStatus = "idle" | "running" | "pausing" | "paused" | "cancelling" | "cancelled" | "completed" | "failed";

export type TaskControlContext = {
    currentTaskId: string | null;
    runStatus: RunStatus;
    isCancelling: boolean;
    blockedTaskId: string | null;
    isPauseLoading: boolean;
    isResumeLoading: boolean;
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
    | { type: "CONTROL_STATE_UPDATED"; cancelled: boolean }
    | { type: "CONTROL_REQUEST_FAILED"; blockCurrentTask?: boolean };

const computeCanControlTask = (
    currentTaskId: string | null,
    runStatus: RunStatus,
    isCancelling: boolean,
    blockedTaskId: string | null,
): boolean => {
    if (!currentTaskId) return false;
    if (runStatus !== "running" && runStatus !== "paused") return false;
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
        CONTROL_STATE_UPDATED: {
            actions: assign(({ context, event }) => {
                const blockedTaskId = event.cancelled ? context.currentTaskId : context.blockedTaskId;
                return {
                    blockedTaskId,
                    isPauseLoading: false,
                    isResumeLoading: false,
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

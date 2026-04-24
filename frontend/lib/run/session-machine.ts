import { assign, createMachine } from "xstate";
import { ControlErrorCode, RunDomainEvent } from "./domain-events";

export type SessionLifecycleState =
    | "idle"
    | "hydrating"
    | "ready"
    | "running"
    | "pausing"
    | "paused"
    | "terminal.completed"
    | "terminal.failed"
    | "terminal.cancelled";

export type SessionErrorCode =
    | "INVALID_TRANSITION"
    | "TASK_NOT_FOUND"
    | "SESSION_MISMATCH"
    | "AUTHZ_DENIED"
    | "CONFLICT"
    | "TIMEOUT"
    | "TRANSPORT_UNAVAILABLE"
    | "INTERNAL";

type SessionMachineContext = {
    sessionId: string | null;
    workflowId: string | null;
    taskId: string | null;
    lastError: {
        code: SessionErrorCode;
        message: string;
    } | null;
};

type SessionMachineEvent =
    | { type: "OPEN_SESSION"; sessionId: string }
    | { type: "REHYDRATE_DONE"; hasActiveWorkflow: boolean; workflowId?: string | null; taskId?: string | null }
    | { type: "CREATE_TASK"; workflowId: string; taskId: string }
    | { type: "DOMAIN_EVENT"; event: RunDomainEvent }
    | { type: "RESET" };

const isControlRejected = (event: RunDomainEvent): event is Extract<RunDomainEvent, { kind: "control.rejected" }> =>
    event.kind === "control.rejected";

const controlCodeToSessionErrorCode = (code: ControlErrorCode): SessionErrorCode => code;

export function createSessionMachine() {
    return createMachine({
        types: {} as {
            context: SessionMachineContext;
            events: SessionMachineEvent;
        },
        context: {
            sessionId: null,
            workflowId: null,
            taskId: null,
            lastError: null,
        },
        initial: "idle",
        states: {
            idle: {
                on: {
                    OPEN_SESSION: {
                        target: "hydrating",
                        actions: assign(({ event }) => ({
                            sessionId: event.sessionId,
                            workflowId: null,
                            taskId: null,
                            lastError: null,
                        })),
                    },
                    RESET: {
                        target: "idle",
                        actions: assign({
                            workflowId: null,
                            taskId: null,
                            lastError: null,
                        }),
                    },
                },
            },
            hydrating: {
                on: {
                    REHYDRATE_DONE: [
                        {
                            guard: ({ event }) => event.hasActiveWorkflow,
                            target: "running",
                            actions: assign(({ event }) => ({
                                workflowId: event.workflowId || null,
                                taskId: event.taskId || event.workflowId || null,
                                lastError: null,
                            })),
                        },
                        {
                            target: "ready",
                            actions: assign({
                                workflowId: null,
                                taskId: null,
                                lastError: null,
                            }),
                        },
                    ],
                    RESET: {
                        target: "idle",
                        actions: assign({
                            workflowId: null,
                            taskId: null,
                            lastError: null,
                        }),
                    },
                },
            },
            ready: {
                on: {
                    CREATE_TASK: {
                        target: "running",
                        actions: assign(({ event }) => ({
                            workflowId: event.workflowId,
                            taskId: event.taskId,
                            lastError: null,
                        })),
                    },
                    DOMAIN_EVENT: [
                        {
                            guard: ({ event }) => event.event.kind === "workflow.started",
                            target: "running",
                            actions: assign(({ event }) => ({
                                workflowId: event.event.workflowId,
                                taskId: event.event.workflowId,
                                lastError: null,
                            })),
                        },
                    ],
                    RESET: {
                        target: "idle",
                        actions: assign({
                            workflowId: null,
                            taskId: null,
                            lastError: null,
                        }),
                    },
                },
            },
            running: {
                on: {
                    DOMAIN_EVENT: [
                        {
                            guard: ({ event }) => event.event.kind === "workflow.completed",
                            target: "terminal.completed",
                            actions: assign({
                                lastError: null,
                            }),
                        },
                        {
                            guard: ({ event }) => event.event.kind === "workflow.failed",
                            target: "terminal.failed",
                        },
                        {
                            guard: ({ event }) => event.event.kind === "control.pause.requested",
                            target: "pausing",
                        },
                        {
                            guard: ({ event }) => event.event.kind === "control.pause.confirmed",
                            target: "paused",
                        },
                        {
                            guard: ({ event }) => event.event.kind === "control.cancel.confirmed",
                            target: "terminal.cancelled",
                        },
                        {
                            guard: ({ event }) => isControlRejected(event.event),
                            actions: assign(({ event }) => ({
                                lastError: {
                                    code: controlCodeToSessionErrorCode(event.event.code),
                                    message: event.event.message,
                                },
                            })),
                        },
                    ],
                    RESET: {
                        target: "idle",
                        actions: assign({
                            workflowId: null,
                            taskId: null,
                            lastError: null,
                        }),
                    },
                },
            },
            pausing: {
                on: {
                    DOMAIN_EVENT: [
                        {
                            guard: ({ event }) => event.event.kind === "control.pause.confirmed",
                            target: "paused",
                        },
                        {
                            guard: ({ event }) => event.event.kind === "control.cancel.confirmed",
                            target: "terminal.cancelled",
                        },
                        {
                            guard: ({ event }) => isControlRejected(event.event),
                            target: "running",
                            actions: assign(({ event }) => ({
                                lastError: {
                                    code: controlCodeToSessionErrorCode(event.event.code),
                                    message: event.event.message,
                                },
                            })),
                        },
                    ],
                    RESET: {
                        target: "idle",
                        actions: assign({
                            workflowId: null,
                            taskId: null,
                            lastError: null,
                        }),
                    },
                },
            },
            paused: {
                on: {
                    DOMAIN_EVENT: [
                        {
                            guard: ({ event }) => event.event.kind === "control.resume.confirmed",
                            target: "running",
                        },
                        {
                            guard: ({ event }) => event.event.kind === "control.cancel.confirmed",
                            target: "terminal.cancelled",
                        },
                        {
                            guard: ({ event }) => isControlRejected(event.event),
                            actions: assign(({ event }) => ({
                                lastError: {
                                    code: controlCodeToSessionErrorCode(event.event.code),
                                    message: event.event.message,
                                },
                            })),
                        },
                    ],
                    RESET: {
                        target: "idle",
                        actions: assign({
                            workflowId: null,
                            taskId: null,
                            lastError: null,
                        }),
                    },
                },
            },
            terminal: {
                initial: "completed",
                states: {
                    completed: {},
                    failed: {},
                    cancelled: {},
                },
                on: {
                    RESET: {
                        target: "idle",
                        actions: assign({
                            workflowId: null,
                            taskId: null,
                            lastError: null,
                        }),
                    },
                },
            },
        },
    });
}

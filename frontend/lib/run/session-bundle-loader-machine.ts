import { assign, createMachine, fromPromise } from "xstate";

export type SessionBundleLoadResult = {
    session: {
        session_id: string;
        first_task_mode?: string;
        is_research_session?: boolean;
        research_strategy?: string;
    };
    conversation: {
        session_id: string;
        messages: Array<{
            id?: string;
            role?: "user" | "assistant" | "system";
            content?: string;
            timestamp?: string;
            task_id?: string;
            metadata?: Record<string, unknown>;
            attachments?: Array<{ file_id: string; filename: string; size: number; mime_type: string }>;
        }>;
    };
    timeline: {
        session_id: string;
        events: Array<Record<string, unknown>>;
    };
    history: {
        session_id: string;
        tasks: Array<{
            task_id?: string;
            workflow_id?: string;
            status?: string;
        }>;
    };
    state?: {
        session_id: string;
        status?: "idle" | "running" | "completed" | "failed" | "paused" | "cancelled" | "canceled";
        active_task_id?: string;
        task_state?: "IDLE" | "RUNNING" | "PAUSED" | "SUCCEEDED" | "FAILED" | "CANCELED";
        session_control_state?: "IDLE" | "ACTIVE_RUNNING" | "ACTIVE_PAUSED" | "TERMINATING";
    };
};

type SessionBundleLoaderContext = {
    sessionId: string | null;
    data: SessionBundleLoadResult | null;
    error: unknown | null;
};

type SessionBundleLoaderEvent =
    | { type: "SYNC_SESSION"; sessionId: string | null }
    | { type: "RETRY" };

export type SessionBundleLoaderDeps = {
    loadBundle: (sessionId: string) => Promise<SessionBundleLoadResult>;
};

export function createSessionBundleLoaderMachine(deps: SessionBundleLoaderDeps) {
    return createMachine({
        types: {} as {
            context: SessionBundleLoaderContext;
            events: SessionBundleLoaderEvent;
        },
        context: {
            sessionId: null,
            data: null,
            error: null,
        },
        initial: "idle",
        states: {
            idle: {
                on: {
                    SYNC_SESSION: [
                        {
                            guard: ({ event }) => !!event.sessionId,
                            target: "loading",
                            actions: assign(({ event }) => ({
                                sessionId: event.sessionId,
                                data: null,
                                error: null,
                            })),
                        },
                        {
                            actions: assign({
                                sessionId: null,
                                data: null,
                                error: null,
                            }),
                        },
                    ],
                },
            },
            loading: {
                invoke: {
                    src: fromPromise(async ({ input }: { input: { sessionId: string } }) => deps.loadBundle(input.sessionId)),
                    input: ({ context }) => ({
                        sessionId: context.sessionId as string,
                    }),
                    onDone: {
                        target: "success",
                        actions: assign(({ event }) => ({
                            data: event.output,
                            error: null,
                        })),
                    },
                    onError: {
                        target: "failure",
                        actions: assign(({ event }) => ({
                            error: event.error,
                            data: null,
                        })),
                    },
                },
                on: {
                    SYNC_SESSION: [
                        {
                            guard: ({ event }) => !!event.sessionId,
                            target: "loading",
                            reenter: true,
                            actions: assign(({ context, event }) => {
                                if (context.sessionId === event.sessionId) {
                                    return {};
                                }
                                return {
                                    sessionId: event.sessionId,
                                    data: null,
                                    error: null,
                                };
                            }),
                        },
                        {
                            target: "idle",
                            actions: assign({
                                sessionId: null,
                                data: null,
                                error: null,
                            }),
                        },
                    ],
                },
            },
            success: {
                on: {
                    SYNC_SESSION: [
                        {
                            guard: ({ event }) => !!event.sessionId,
                            target: "loading",
                            actions: assign(({ event }) => ({
                                sessionId: event.sessionId,
                                data: null,
                                error: null,
                            })),
                        },
                        {
                            target: "idle",
                            actions: assign({
                                sessionId: null,
                                data: null,
                                error: null,
                            }),
                        },
                    ],
                    RETRY: {
                        target: "loading",
                    },
                },
            },
            failure: {
                on: {
                    SYNC_SESSION: [
                        {
                            guard: ({ event }) => !!event.sessionId,
                            target: "loading",
                            actions: assign(({ event }) => ({
                                sessionId: event.sessionId,
                                data: null,
                                error: null,
                            })),
                        },
                        {
                            target: "idle",
                            actions: assign({
                                sessionId: null,
                                data: null,
                                error: null,
                            }),
                        },
                    ],
                    RETRY: {
                        guard: ({ context }) => !!context.sessionId,
                        target: "loading",
                        actions: assign({
                            error: null,
                        }),
                    },
                },
            },
        },
    });
}

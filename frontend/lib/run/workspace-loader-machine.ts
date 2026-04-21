import { assign, createMachine, fromPromise } from "xstate";
import { CardData } from "./types";

export type WorkspacePhase = "idle" | "clearing" | "loading" | "hydrated" | "empty" | "error";

export type WorkspaceLoadResult = {
    sessionId: string;
    cards: CardData[];
    projectionStatus?: "hydrated" | "empty";
    templateId?: string;
    supportedQuestionTypes?: string[];
};

type WorkspaceLoaderContext = {
    sessionId: string | null;
    data: WorkspaceLoadResult | null;
    error: string | null;
};

type WorkspaceLoaderEvent =
    | { type: "SYNC_SESSION"; sessionId: string | null }
    | { type: "REFRESH" }
    | { type: "RETRY" };

export type WorkspaceLoaderDeps = {
    loadWorkspace: (sessionId: string) => Promise<WorkspaceLoadResult>;
};

const toPhase = (state: "idle" | "loading" | "success" | "failure", data: WorkspaceLoadResult | null): WorkspacePhase => {
    if (state === "idle") return "idle";
    if (state === "loading") return "loading";
    if (state === "failure") return "error";

    if (!data) return "empty";
    if (data.projectionStatus === "hydrated") return "hydrated";
    if (data.projectionStatus === "empty") return "empty";
    return data.cards.length > 0 ? "hydrated" : "empty";
};

export const inferWorkspacePhaseFromData = (data: WorkspaceLoadResult | null): WorkspacePhase => toPhase("success", data);

export function createWorkspaceLoaderMachine(deps: WorkspaceLoaderDeps) {
    return createMachine({
        types: {} as {
            context: WorkspaceLoaderContext;
            events: WorkspaceLoaderEvent;
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
                    src: fromPromise(async ({ input }: { input: { sessionId: string } }) => deps.loadWorkspace(input.sessionId)),
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
                            error: event.error instanceof Error ? event.error.message : "Failed to load workspace",
                            data: null,
                        })),
                    },
                },
                on: {
                    SYNC_SESSION: [
                        {
                            guard: ({ event }) => !!event.sessionId,
                            target: "loading",
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
                            reenter: true,
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
                    REFRESH: {
                        guard: ({ context }) => !!context.sessionId,
                        target: "loading",
                        actions: assign({
                            error: null,
                        }),
                        reenter: true,
                    },
                },
            },
            success: {
                on: {
                    SYNC_SESSION: [
                        {
                            guard: ({ event }) => !!event.sessionId,
                            target: "loading",
                            actions: assign(({ context, event }) => {
                                if (context.sessionId === event.sessionId) {
                                    return { error: null };
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
                    REFRESH: {
                        guard: ({ context }) => !!context.sessionId,
                        target: "loading",
                        actions: assign({
                            error: null,
                        }),
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
                    REFRESH: {
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

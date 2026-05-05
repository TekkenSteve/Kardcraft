import { assign, setup, fromCallback, fromPromise } from "xstate";
import type { ActorRefFrom, SnapshotFrom } from "xstate";
import type { Session } from "@/lib/kratos/client";
import {
    createBrowserSessionAuthClient,
    type SessionAuthClient,
    type SessionLoginRequest,
} from "./auth-client";

type SessionOperation = "check" | "login" | "logout" | null;

export type SessionContext = {
    session: Session | null;
    pendingLogin: SessionLoginRequest | null;
    lastError: unknown | null;
    lastOperation: SessionOperation;
};

export type SessionEvent =
    | { type: "CHECK" }
    | { type: "AUTH_CHANGED" }
    | { type: "LOGIN"; request: SessionLoginRequest }
    | { type: "LOGOUT" }
    | { type: "CLEAR_ERROR" };

export function createSessionMachine(
    authClient: SessionAuthClient = createBrowserSessionAuthClient(),
) {
    return setup({
        types: {} as {
            context: SessionContext;
            events: SessionEvent;
        },
        actors: {
            checkSession: fromPromise(async () => authClient.getSession()),
            login: fromPromise(async ({ input }: { input: SessionLoginRequest }) => {
                await authClient.login(input);
                return authClient.getSession();
            }),
            logout: fromPromise(async () => {
                await authClient.logout();
            }),
            authStateListener: fromCallback(({ sendBack }) => {
                const unsubscribe = authClient.onAuthStateChanged(() => {
                    sendBack({ type: "AUTH_CHANGED" });
                });

                return () => unsubscribe();
            }),
        },
        guards: {
            hasSession: ({ event }) => "output" in event && !!event.output,
        },
        actions: {
            storePendingLogin: assign(({ event }) => {
                if (event.type !== "LOGIN") return {};
                return {
                    pendingLogin: event.request,
                    lastError: null,
                    lastOperation: "login" as const,
                };
            }),
            clearError: assign({
                lastError: null,
            }),
            clearPendingLogin: assign({
                pendingLogin: null,
            }),
            assignCheckedSession: assign(({ event }) => ({
                session: "output" in event ? (event.output as Session | null) : null,
                lastError: null,
                lastOperation: "check" as const,
            })),
            clearSessionAfterCheck: assign({
                session: null,
                lastError: null,
                lastOperation: "check",
            }),
            assignCheckError: assign(({ event }) => ({
                session: null,
                lastError: "error" in event ? event.error : null,
                lastOperation: "check" as const,
            })),
            assignLoginError: assign(({ event }) => ({
                session: null,
                lastError: "error" in event ? event.error : null,
                lastOperation: "login" as const,
            })),
            assignSessionAfterLogin: assign(({ event }) => ({
                session: "output" in event ? (event.output as Session | null) : null,
                lastError: null,
                lastOperation: "login" as const,
            })),
            assignLoginMissingSession: assign({
                session: null,
                lastError: new Error("Login succeeded but no active session was returned."),
                lastOperation: "login",
            }),
            assignLogoutSuccess: assign({
                session: null,
                lastError: null,
                lastOperation: "logout",
            }),
            assignLogoutError: assign(({ event }) => ({
                session: null,
                lastError: "error" in event ? event.error : null,
                lastOperation: "logout" as const,
            })),
        },
    }).createMachine({
        id: "session",
        initial: "idle",
        context: {
            session: null,
            pendingLogin: null,
            lastError: null,
            lastOperation: null,
        },
        states: {
            checking: {
                invoke: {
                    src: "checkSession",
                    onDone: [
                        {
                            guard: "hasSession",
                            target: "authenticated",
                            actions: "assignCheckedSession",
                        },
                        {
                            target: "idle",
                            actions: "clearSessionAfterCheck",
                        },
                    ],
                    onError: {
                        target: "idle",
                        actions: "assignCheckError",
                    },
                },
            },
            idle: {
                invoke: {
                    id: "auth-state-listener",
                    src: "authStateListener",
                },
                on: {
                    CHECK: {
                        target: "checking",
                    },
                    AUTH_CHANGED: {
                        target: "checking",
                    },
                    LOGIN: {
                        target: "authenticating",
                        actions: "storePendingLogin",
                    },
                    CLEAR_ERROR: {
                        actions: "clearError",
                    },
                },
            },
            authenticating: {
                invoke: {
                    id: "login-request",
                    src: "login",
                    input: ({ context }) => context.pendingLogin as SessionLoginRequest,
                    onDone: [
                        {
                            guard: "hasSession",
                            target: "authenticated",
                            actions: ["clearPendingLogin", "assignSessionAfterLogin"],
                        },
                        {
                            target: "idle",
                            actions: ["clearPendingLogin", "assignLoginMissingSession"],
                        },
                    ],
                    onError: {
                        target: "idle",
                        actions: ["clearPendingLogin", "assignLoginError"],
                    },
                },
            },
            authenticated: {
                invoke: {
                    id: "auth-state-listener",
                    src: "authStateListener",
                },
                on: {
                    CHECK: {
                        target: "checking",
                    },
                    AUTH_CHANGED: {
                        target: "checking",
                    },
                    LOGIN: {
                        target: "authenticating",
                        actions: "storePendingLogin",
                    },
                    LOGOUT: {
                        target: "refreshing",
                        actions: "clearError",
                    },
                    CLEAR_ERROR: {
                        actions: "clearError",
                    },
                },
            },
            refreshing: {
                invoke: {
                    id: "logout-request",
                    src: "logout",
                    onDone: {
                        target: "idle",
                        actions: "assignLogoutSuccess",
                    },
                    onError: {
                        target: "idle",
                        actions: "assignLogoutError",
                    },
                },
            },
        },
    });
}

export type SessionMachine = ReturnType<typeof createSessionMachine>;
export type SessionActorRef = ActorRefFrom<SessionMachine>;
export type SessionSnapshot = SnapshotFrom<SessionMachine>;

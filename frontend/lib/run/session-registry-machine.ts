import { assign, createMachine } from "xstate";
import {
    AgentType,
    CardData,
    createInitialSessionState,
    DEFAULT_TEMPLATE_PREFLIGHT,
    ResearchStrategy,
    RunMessage,
    RunSessionState,
    toSessionKey,
    isDraftSessionId,
} from "./types";
import { RunEvent } from "@/lib/kardcraft/types";

export type SessionRegistryContext = {
    sessions: Record<string, RunSessionState>;
    activeSessionKey: string;
    selectedAgent: AgentType;
    researchStrategy: ResearchStrategy;
};

export type SessionRegistryEvent =
    | { type: "ACTIVATE_SESSION"; sessionId: string | null }
    | { type: "PROMOTE_SESSION"; fromSessionId: string | null; toSessionId: string }
    | { type: "SET_SELECTED_AGENT"; value: AgentType }
    | { type: "SET_RESEARCH_STRATEGY"; value: ResearchStrategy }
    | { type: "RESET_SESSION"; sessionId: string | null }
    | { type: "SET_MAIN_WORKFLOW_ID"; sessionId: string | null; workflowId: string | null }
    | { type: "SET_STATUS"; sessionId: string | null; status: RunSessionState["status"] }
    | { type: "SET_RUN_PHASE"; sessionId: string | null; phase: RunSessionState["runPhase"] }
    | { type: "SET_CONNECTION_STATE"; sessionId: string | null; connectionState: RunSessionState["connectionState"] }
    | { type: "SET_STREAM_ERROR"; sessionId: string | null; error: string | null }
    | { type: "SET_SESSION_TITLE"; sessionId: string | null; title: string | null }
    | { type: "SET_PAUSED"; sessionId: string | null; paused: boolean; checkpoint?: string | null; reason?: string | null }
    | { type: "SET_CANCELLING"; sessionId: string | null; value: boolean }
    | { type: "SET_CANCELLED"; sessionId: string | null; value: boolean }
    | { type: "SET_TEMPLATE_PREFLIGHT"; sessionId: string | null; value: RunSessionState["templatePreflight"] }
    | { type: "CLEAR_TEMPLATE_PREFLIGHT"; sessionId: string | null }
    | { type: "SET_CARDS"; sessionId: string | null; cards: CardData[] }
    | { type: "UPSERT_CARDS_BATCH"; sessionId: string | null; cards: CardData[] }
    | { type: "UPDATE_CARD_STATUS"; sessionId: string | null; cardId: string; status: CardData["edit_state"]["status"] }
    | { type: "UPDATE_CARD_QUESTION_TYPE"; sessionId: string | null; cardId: string; questionType: CardData["content"]["model"] }
    | { type: "BULK_UPDATE_STATUS"; sessionId: string | null; cardIds: string[]; status: CardData["edit_state"]["status"] }
    | { type: "ADD_MESSAGE"; sessionId: string | null; message: RunMessage }
    | { type: "UPSERT_MESSAGE"; sessionId: string | null; message: RunMessage }
    | { type: "CLEAR_GENERATING_MESSAGES"; sessionId: string | null; taskId?: string | null }
    | { type: "CLEAR_STATUS_MESSAGES"; sessionId: string | null; taskId?: string | null }
    | { type: "ADD_EVENT"; sessionId: string | null; event: RunEvent };

const ensureSession = (
    sessions: Record<string, RunSessionState>,
    sessionId: string | null,
): [string, RunSessionState] => {
    const key = toSessionKey(sessionId);
    const existing = sessions[key];
    if (existing) return [key, existing];
    const normalizedSessionId = sessionId && sessionId !== "new" && !isDraftSessionId(sessionId) ? sessionId : null;
    return [key, createInitialSessionState(key, normalizedSessionId)];
};

export function createSessionRegistryMachine() {
    return createMachine({
        types: {} as {
            context: SessionRegistryContext;
            events: SessionRegistryEvent;
        },
        context: {
            sessions: {},
            activeSessionKey: toSessionKey("new"),
            selectedAgent: "normal",
            researchStrategy: "quick",
        },
        initial: "active",
        states: {
            active: {
                on: {
                    ACTIVATE_SESSION: {
                actions: assign(({ context, event }) => {
                    const key = toSessionKey(event.sessionId);
                    if (context.sessions[key]) {
                        return { activeSessionKey: key };
                    }
                    return {
                        activeSessionKey: key,
                        sessions: {
                            ...context.sessions,
                            [key]: createInitialSessionState(
                                key,
                                event.sessionId && event.sessionId !== "new" && !isDraftSessionId(event.sessionId) ? event.sessionId : null,
                            ),
                        },
                    };
                }),
                    },
                    PROMOTE_SESSION: {
                actions: assign(({ context, event }) => {
                    const fromKey = toSessionKey(event.fromSessionId);
                    const toKey = toSessionKey(event.toSessionId);
                    if (fromKey === toKey) return {};

                    const source = context.sessions[fromKey] || createInitialSessionState(fromKey, null);
                    const nextSession: RunSessionState = {
                        ...source,
                        sessionKey: toKey,
                        sessionId: event.toSessionId,
                    };

                    const sessions = { ...context.sessions };
                    delete sessions[fromKey];
                    sessions[toKey] = nextSession;

                    return {
                        sessions,
                        activeSessionKey: context.activeSessionKey === fromKey ? toKey : context.activeSessionKey,
                    };
                }),
                    },
                    SET_SELECTED_AGENT: {
                actions: assign(({ event }) => ({ selectedAgent: event.value })),
                    },
                    SET_RESEARCH_STRATEGY: {
                actions: assign(({ event }) => ({ researchStrategy: event.value })),
                    },
                    RESET_SESSION: {
                actions: assign(({ context, event }) => {
                    const [key] = ensureSession(context.sessions, event.sessionId);
                    return {
                        sessions: {
                            ...context.sessions,
                            [key]: createInitialSessionState(
                                key,
                                event.sessionId && event.sessionId !== "new" && !isDraftSessionId(event.sessionId) ? event.sessionId : null,
                            ),
                        },
                    };
                }),
                    },
                    SET_MAIN_WORKFLOW_ID: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    return { sessions: { ...context.sessions, [key]: { ...session, mainWorkflowId: event.workflowId } } };
                }),
                    },
                    SET_STATUS: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    return { sessions: { ...context.sessions, [key]: { ...session, status: event.status } } };
                }),
                    },
                    SET_RUN_PHASE: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    return { sessions: { ...context.sessions, [key]: { ...session, runPhase: event.phase } } };
                }),
                    },
                    SET_CONNECTION_STATE: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    return {
                        sessions: {
                            ...context.sessions,
                            [key]: {
                                ...session,
                                connectionState: event.connectionState,
                                streamError: event.connectionState === "connected" ? null : session.streamError,
                            },
                        },
                    };
                }),
                    },
                    SET_STREAM_ERROR: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    return {
                        sessions: {
                            ...context.sessions,
                            [key]: {
                                ...session,
                                streamError: event.error,
                                connectionState: event.error ? "error" : session.connectionState,
                            },
                        },
                    };
                }),
                    },
                    SET_SESSION_TITLE: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    return { sessions: { ...context.sessions, [key]: { ...session, sessionTitle: event.title } } };
                }),
                    },
                    SET_PAUSED: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    return {
                        sessions: {
                            ...context.sessions,
                            [key]: {
                                ...session,
                                isPaused: event.paused,
                                pauseCheckpoint: event.checkpoint ?? null,
                                pauseReason: event.reason ?? null,
                            },
                        },
                    };
                }),
                    },
                    SET_CANCELLING: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    return { sessions: { ...context.sessions, [key]: { ...session, isCancelling: event.value } } };
                }),
                    },
                    SET_CANCELLED: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    return {
                        sessions: {
                            ...context.sessions,
                            [key]: {
                                ...session,
                                isCancelled: event.value,
                                isCancelling: false,
                                status: event.value ? "failed" : session.status,
                            },
                        },
                    };
                }),
                    },
                    SET_TEMPLATE_PREFLIGHT: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    return { sessions: { ...context.sessions, [key]: { ...session, templatePreflight: event.value } } };
                }),
                    },
                    CLEAR_TEMPLATE_PREFLIGHT: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    return { sessions: { ...context.sessions, [key]: { ...session, templatePreflight: { ...DEFAULT_TEMPLATE_PREFLIGHT } } } };
                }),
                    },
                    SET_CARDS: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    return { sessions: { ...context.sessions, [key]: { ...session, cards: event.cards, cardsVersion: session.cardsVersion + 1 } } };
                }),
                    },
                    UPSERT_CARDS_BATCH: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    const byId = new Map(session.cards.map((card) => [card.card_id, card]));
                    event.cards.forEach((card) => {
                        if (!card?.card_id) return;
                        byId.set(card.card_id, card);
                    });
                    return {
                        sessions: {
                            ...context.sessions,
                            [key]: {
                                ...session,
                                cards: Array.from(byId.values()),
                                cardsVersion: session.cardsVersion + 1,
                            },
                        },
                    };
                }),
                    },
                    UPDATE_CARD_STATUS: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    return {
                        sessions: {
                            ...context.sessions,
                            [key]: {
                                ...session,
                                cards: session.cards.map((card) =>
                                    card.card_id === event.cardId
                                        ? { ...card, edit_state: { ...card.edit_state, status: event.status } }
                                        : card,
                                ),
                                cardsVersion: session.cardsVersion + 1,
                            },
                        },
                    };
                }),
                    },
                    UPDATE_CARD_QUESTION_TYPE: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    return {
                        sessions: {
                            ...context.sessions,
                            [key]: {
                                ...session,
                                cards: session.cards.map((card) =>
                                    card.card_id === event.cardId
                                        ? {
                                              ...card,
                                              content: {
                                                  ...card.content,
                                                  model: event.questionType,
                                              },
                                          }
                                        : card,
                                ),
                                cardsVersion: session.cardsVersion + 1,
                            },
                        },
                    };
                }),
                    },
                    BULK_UPDATE_STATUS: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    const idSet = new Set(event.cardIds);
                    return {
                        sessions: {
                            ...context.sessions,
                            [key]: {
                                ...session,
                                cards: session.cards.map((card) =>
                                    idSet.has(card.card_id)
                                        ? { ...card, edit_state: { ...card.edit_state, status: event.status } }
                                        : card,
                                ),
                                cardsVersion: session.cardsVersion + 1,
                            },
                        },
                    };
                }),
                    },
                    ADD_MESSAGE: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    if (session.messages.some((item) => item.id === event.message.id)) {
                        return {};
                    }
                    return { sessions: { ...context.sessions, [key]: { ...session, messages: [...session.messages, event.message] } } };
                }),
                    },
                    UPSERT_MESSAGE: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    const existingIndex = session.messages.findIndex((item) => item.id === event.message.id);
                    if (existingIndex < 0) {
                        return { sessions: { ...context.sessions, [key]: { ...session, messages: [...session.messages, event.message] } } };
                    }
                    const nextMessages = [...session.messages];
                    nextMessages[existingIndex] = event.message;
                    return { sessions: { ...context.sessions, [key]: { ...session, messages: nextMessages } } };
                }),
                    },
                    CLEAR_GENERATING_MESSAGES: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    const nextMessages = session.messages.filter((message) => {
                        if (!message.isGenerating) return true;
                        if (!event.taskId) return false;
                        return message.taskId !== event.taskId;
                    });
                    return { sessions: { ...context.sessions, [key]: { ...session, messages: nextMessages } } };
                }),
                    },
                    CLEAR_STATUS_MESSAGES: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    const nextMessages = session.messages.filter((message) => {
                        if (message.role !== "status") return true;
                        if (!event.taskId) return false;
                        return message.taskId !== event.taskId;
                    });
                    return { sessions: { ...context.sessions, [key]: { ...session, messages: nextMessages } } };
                }),
                    },
                    ADD_EVENT: {
                actions: assign(({ context, event }) => {
                    const [key, session] = ensureSession(context.sessions, event.sessionId);
                    const duplicated = event.event.stream_id
                        ? session.events.some((item) => item.stream_id === event.event.stream_id && item.workflow_id === event.event.workflow_id)
                        : false;
                    if (duplicated) return {};
                    return { sessions: { ...context.sessions, [key]: { ...session, events: [...session.events, event.event] } } };
                }),
                    },
                },
            },
        },
    });
}

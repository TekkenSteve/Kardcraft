"use client";

import React, { createContext, useContext, useMemo } from "react";
import { createActor } from "xstate";
import { useSelector } from "@xstate/react";
import { RunEvent } from "@/lib/kardcraft/types";
import {
    AgentType,
    CardData,
    createInitialSessionState,
    RegistryViewModel,
    ResearchStrategy,
    RunMessage,
    RunSessionState,
    SessionViewModel,
    toSessionKey,
    isDraftSessionId,
} from "./types";
import { createSessionRegistryMachine, SessionRegistryContext } from "./session-registry-machine";

type SessionRegistryMachine = ReturnType<typeof createSessionRegistryMachine>;
type SessionRegistryActorRef = ReturnType<typeof createActor<SessionRegistryMachine>>;

const RunSystemContext = createContext<SessionRegistryActorRef | null>(null);
let runSystemActorSingleton: SessionRegistryActorRef | null = null;

const getRunSystemActor = (): SessionRegistryActorRef => {
    if (runSystemActorSingleton) return runSystemActorSingleton;
    const actor = createActor(createSessionRegistryMachine());
    actor.start();
    runSystemActorSingleton = actor;
    return actor;
};

export function RunSystemProvider({ children }: { children: React.ReactNode }) {
    const registryActor = React.useMemo(() => getRunSystemActor(), []);

    return <RunSystemContext.Provider value={registryActor}>{children}</RunSystemContext.Provider>;
}

export function useRunActor() {
    const actor = useContext(RunSystemContext);
    if (!actor) {
        throw new Error("useRunActor must be used within RunSystemProvider");
    }
    return actor;
}

export function useRunSelector<T>(selector: (state: SessionRegistryContext) => T): T {
    const actor = useRunActor();
    return useSelector(actor, (snapshot) => selector(snapshot.context));
}

export function useRunSession(sessionId: string | null | undefined): RunSessionState {
    const key = toSessionKey(sessionId ?? null);
    const normalizedSessionId = sessionId && sessionId !== "new" && !isDraftSessionId(sessionId) ? sessionId : null;
    return useRunSelector((ctx) => ctx.sessions[key] || createInitialSessionState(key, normalizedSessionId));
}

export function useSessionViewModel(sessionId: string | null | undefined): SessionViewModel {
    return useRunSession(sessionId);
}

export function useActiveRunSession(): RunSessionState {
    return useRunSelector((ctx) => ctx.sessions[ctx.activeSessionKey] || createInitialSessionState(ctx.activeSessionKey, null));
}

export function useRegistryViewModel(): RegistryViewModel {
    return useRunSelector((ctx) => {
        const sessions = Object.values(ctx.sessions).map((session) => ({
            sessionKey: session.sessionKey,
            sessionId: session.sessionId,
            status: session.status,
            runPhase: session.runPhase,
            connectionState: session.connectionState,
            sessionTitle: session.sessionTitle,
            mainWorkflowId: session.mainWorkflowId,
        }));

        return {
            activeSessionKey: ctx.activeSessionKey,
            selectedAgent: ctx.selectedAgent,
            researchStrategy: ctx.researchStrategy,
            sessionKeys: sessions.map((item) => item.sessionKey),
            sessions,
        };
    });
}

export function useRunCommands() {
    const actor = useRunActor();
    return useMemo(() => ({
        activateSession: (sessionId: string | null) => actor.send({ type: "ACTIVATE_SESSION", sessionId }),
        promoteSession: (fromSessionId: string | null, toSessionId: string) => actor.send({ type: "PROMOTE_SESSION", fromSessionId, toSessionId }),
        setSelectedAgent: (value: AgentType) => actor.send({ type: "SET_SELECTED_AGENT", value }),
        setResearchStrategy: (value: ResearchStrategy) => actor.send({ type: "SET_RESEARCH_STRATEGY", value }),
        resetSession: (sessionId: string | null) => actor.send({ type: "RESET_SESSION", sessionId }),
        setMainWorkflowId: (sessionId: string | null, workflowId: string | null) => actor.send({ type: "SET_MAIN_WORKFLOW_ID", sessionId, workflowId }),
        setStatus: (sessionId: string | null, status: RunSessionState["status"]) => actor.send({ type: "SET_STATUS", sessionId, status }),
        setRunPhase: (sessionId: string | null, phase: RunSessionState["runPhase"]) => actor.send({ type: "SET_RUN_PHASE", sessionId, phase }),
        setConnectionState: (sessionId: string | null, connectionState: RunSessionState["connectionState"]) =>
            actor.send({ type: "SET_CONNECTION_STATE", sessionId, connectionState }),
        setStreamError: (sessionId: string | null, error: string | null) => actor.send({ type: "SET_STREAM_ERROR", sessionId, error }),
        setSessionTitle: (sessionId: string | null, title: string | null) => actor.send({ type: "SET_SESSION_TITLE", sessionId, title }),
        setPaused: (sessionId: string | null, paused: boolean, checkpoint?: string | null, reason?: string | null) =>
            actor.send({ type: "SET_PAUSED", sessionId, paused, checkpoint, reason }),
        setCancelling: (sessionId: string | null, value: boolean) => actor.send({ type: "SET_CANCELLING", sessionId, value }),
        setCancelled: (sessionId: string | null, value: boolean) => actor.send({ type: "SET_CANCELLED", sessionId, value }),
        setTemplatePreflight: (sessionId: string | null, value: RunSessionState["templatePreflight"]) =>
            actor.send({ type: "SET_TEMPLATE_PREFLIGHT", sessionId, value }),
        clearTemplatePreflight: (sessionId: string | null) => actor.send({ type: "CLEAR_TEMPLATE_PREFLIGHT", sessionId }),
        setCards: (sessionId: string | null, cards: CardData[]) => actor.send({ type: "SET_CARDS", sessionId, cards }),
        upsertCardsBatch: (sessionId: string | null, cards: CardData[]) => actor.send({ type: "UPSERT_CARDS_BATCH", sessionId, cards }),
        updateCardStatus: (sessionId: string | null, cardId: string, status: CardData["edit_state"]["status"]) =>
            actor.send({ type: "UPDATE_CARD_STATUS", sessionId, cardId, status }),
        updateCardQuestionType: (sessionId: string | null, cardId: string, questionType: CardData["content"]["model"]) =>
            actor.send({ type: "UPDATE_CARD_QUESTION_TYPE", sessionId, cardId, questionType }),
        bulkUpdateStatus: (sessionId: string | null, cardIds: string[], status: CardData["edit_state"]["status"]) =>
            actor.send({ type: "BULK_UPDATE_STATUS", sessionId, cardIds, status }),
        addMessage: (sessionId: string | null, message: RunMessage) => actor.send({ type: "ADD_MESSAGE", sessionId, message }),
        upsertMessage: (sessionId: string | null, message: RunMessage) => actor.send({ type: "UPSERT_MESSAGE", sessionId, message }),
        clearGeneratingMessages: (sessionId: string | null, taskId?: string | null) =>
            actor.send({ type: "CLEAR_GENERATING_MESSAGES", sessionId, taskId }),
        clearStatusMessages: (sessionId: string | null, taskId?: string | null) =>
            actor.send({ type: "CLEAR_STATUS_MESSAGES", sessionId, taskId }),
        addEvent: (sessionId: string | null, event: RunEvent) => actor.send({ type: "ADD_EVENT", sessionId, event }),
    }), [actor]);
}

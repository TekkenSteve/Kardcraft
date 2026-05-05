"use client";

import React, { createContext, useContext, useEffect, useMemo } from "react";
import { useSelector } from "@xstate/react";
import { createActor } from "xstate";
import {
    createSessionMachine,
    type SessionActorRef,
    type SessionEvent,
    type SessionSnapshot,
} from "./session-machine";
import type { SessionLoginRequest } from "./auth-client";

const SessionActorContext = createContext<SessionActorRef | null>(null);
let sessionActorSingleton: SessionActorRef | null = null;

function getSessionActor(): SessionActorRef {
    if (sessionActorSingleton) return sessionActorSingleton;

    const actor = createActor(createSessionMachine());
    sessionActorSingleton = actor;
    return actor;
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
    const actor = useMemo(() => getSessionActor(), []);

    useEffect(() => {
        actor.start();
        actor.send({ type: "CHECK" });
    }, [actor]);

    return (
        <SessionActorContext.Provider value={actor}>
            {children}
        </SessionActorContext.Provider>
    );
}

export function useSessionActor(): SessionActorRef {
    const actor = useContext(SessionActorContext);
    if (!actor) {
        throw new Error("useSessionActor must be used within SessionProvider");
    }
    return actor;
}

export function useSessionSelector<T>(selector: (snapshot: SessionSnapshot) => T): T {
    const actor = useSessionActor();
    return useSelector(actor, selector);
}

type SessionCommands = {
    check: () => void;
    login: (request: SessionLoginRequest) => void;
    logout: () => void;
    clearError: () => void;
    send: (event: SessionEvent) => void;
};

export function useSessionCommands(): SessionCommands {
    const actor = useSessionActor();

    return useMemo(
        () => ({
            check: () => actor.send({ type: "CHECK" }),
            login: (request) => actor.send({ type: "LOGIN", request }),
            logout: () => actor.send({ type: "LOGOUT" }),
            clearError: () => actor.send({ type: "CLEAR_ERROR" }),
            send: (event) => actor.send(event),
        }),
        [actor],
    );
}

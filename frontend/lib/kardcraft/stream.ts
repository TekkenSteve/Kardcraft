"use client";

import { RunDomainEvent } from "@/lib/run/domain-events";
import { createStreamActorMachine } from "@/lib/run/stream-actor";
import { CardData } from "@/lib/run/types";
import { useEffect, useRef } from "react";
import { createActor } from "xstate";
import { getStreamUrl } from "./api";

export type RunStreamHandlers = {
    onConnectionState: (value: "idle" | "connecting" | "connected" | "reconnecting" | "error") => void;
    onStreamError: (value: string | null) => void;
    onDomainEvent: (event: RunDomainEvent) => void;
    onCardsBatch: (cards: CardData[]) => void;
};

export function useRunStream(workflowId: string | null, handlers: RunStreamHandlers, restartKey: number = 0) {
    const actorRef = useRef<ReturnType<typeof createActor<ReturnType<typeof createStreamActorMachine>>> | null>(null);
    const handlersRef = useRef(handlers);

    useEffect(() => {
        handlersRef.current = handlers;
    }, [handlers]);

    useEffect(() => {
        if (!workflowId) return;

        const machine = createStreamActorMachine({
            getStreamUrl,
            createEventSource: (url: string) => new EventSource(url, { withCredentials: true }),
            nowIso: () => new Date().toISOString(),
            onConnectionState: (value) => {
                handlersRef.current.onConnectionState(value);
            },
            onStreamError: (value) => {
                handlersRef.current.onStreamError(value);
            },
            onDomainEvent: (event) => {
                handlersRef.current.onDomainEvent(event);
            },
            onCardsBatch: (cards: CardData[]) => {
                handlersRef.current.onCardsBatch(cards);
            },
            onRejectWireEvent: ({ type, reason, details }) => {
                console.warn("[useRunStream] Rejected wire event at domain boundary", { type, reason, details });
            },
        });
        const actor = createActor(machine);
        actorRef.current = actor;
        actor.start();
        actor.send({ type: "START", workflowId, restartKey });

        return () => {
            actor.send({ type: "STOP" });
            actor.stop();
            actorRef.current = null;
        };
    }, [workflowId, restartKey]);
}

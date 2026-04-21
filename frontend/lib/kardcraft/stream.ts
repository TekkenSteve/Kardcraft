"use client";

import { useEffect, useRef } from "react";
import { getStreamUrl } from "./api";
import { CardData } from "@/lib/run/types";
import { RunDomainEvent } from "@/lib/run/domain-events";
import { createStreamActorMachine } from "@/lib/run/stream-actor";
import { createActor } from "xstate";

type RunStreamHandlers = {
    onConnectionState: (value: "idle" | "connecting" | "connected" | "reconnecting" | "error") => void;
    onStreamError: (value: string | null) => void;
    onDomainEvent: (event: RunDomainEvent) => void;
    onCardsBatch: (cards: CardData[]) => void;
};

export function useRunStream(workflowId: string | null, handlers: RunStreamHandlers, restartKey: number = 0) {
    const actorRef = useRef<ReturnType<typeof createActor<ReturnType<typeof createStreamActorMachine>>> | null>(null);

    useEffect(() => {
        if (!workflowId) return;

        const machine = createStreamActorMachine({
            getStreamUrl,
            createEventSource: (url: string) => new EventSource(url, { withCredentials: true }),
            nowIso: () => new Date().toISOString(),
            onConnectionState: handlers.onConnectionState,
            onStreamError: handlers.onStreamError,
            onDomainEvent: handlers.onDomainEvent,
            onCardsBatch: (cards: CardData[]) => handlers.onCardsBatch(cards),
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
    }, [workflowId, restartKey, handlers]);
}

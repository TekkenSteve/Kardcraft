import { describe, expect, it, vi } from "vitest";
import { createActor } from "xstate";
import { createStreamActorMachine, EventSourceLike } from "./stream-actor";

class FakeEventSource implements EventSourceLike {
    readyState = 0;
    onopen: ((event: Event) => void) | null = null;
    onmessage: ((event: MessageEvent) => void) | null = null;
    onerror: ((event: Event) => void) | null = null;
    private listeners = new Map<string, Array<(event: Event | MessageEvent) => void>>();

    addEventListener(type: string, listener: (event: Event | MessageEvent) => void) {
        const existing = this.listeners.get(type) || [];
        existing.push(listener);
        this.listeners.set(type, existing);
    }

    close() {
        this.readyState = 2;
    }

    emitOpen() {
        this.readyState = 1;
        this.onopen?.(new Event("open"));
    }

    emit(type: string, payload: Record<string, unknown>) {
        const event = {
            data: JSON.stringify(payload),
            lastEventId: typeof payload.stream_id === "string" ? payload.stream_id : "",
        } as MessageEvent;
        const listeners = this.listeners.get(type) || [];
        listeners.forEach((listener) => listener(event));
    }

    emitError() {
        this.onerror?.(new Event("error"));
    }
}

describe("stream actor machine", () => {
    it("maps workflow events into domain events", async () => {
        const fake = new FakeEventSource();
        const onDomainEvent = vi.fn();
        const machine = createStreamActorMachine({
            getStreamUrl: () => "http://localhost/stream?workflow_id=wf-1",
            createEventSource: () => fake,
            nowIso: () => "2026-01-01T00:00:00.000Z",
            onConnectionState: vi.fn(),
            onStreamError: vi.fn(),
            onDomainEvent,
            onCardsBatch: vi.fn(),
            onRejectWireEvent: vi.fn(),
        });

        const actor = createActor(machine);
        actor.start();
        actor.send({ type: "START", workflowId: "wf-1", restartKey: 0 });
        fake.emitOpen();

        fake.emit("WORKFLOW_STARTED", {
            type: "WORKFLOW_STARTED",
            workflow_id: "wf-1",
            stream_id: "s-1",
        });

        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(onDomainEvent).toHaveBeenCalledTimes(1);
        expect(onDomainEvent.mock.calls[0][0].kind).toBe("workflow.started");
        actor.stop();
    });

    it("emits card batches for CARD_UPDATED", async () => {
        const fake = new FakeEventSource();
        const onCardsBatch = vi.fn();
        const machine = createStreamActorMachine({
            getStreamUrl: () => "http://localhost/stream?workflow_id=wf-1",
            createEventSource: () => fake,
            nowIso: () => "2026-01-01T00:00:00.000Z",
            onConnectionState: vi.fn(),
            onStreamError: vi.fn(),
            onDomainEvent: vi.fn(),
            onCardsBatch,
            onRejectWireEvent: vi.fn(),
        });

        const actor = createActor(machine);
        actor.start();
        actor.send({ type: "START", workflowId: "wf-1", restartKey: 0 });
        fake.emitOpen();

        fake.emit("CARD_UPDATED", {
            type: "CARD_UPDATED",
            card_id: "card-1",
            content: { version: 1, model: "mcq", data: { front: "Q", back: "A" } },
            edit_state: { status: "draft" },
            concepts: [],
            meta: { created_at: "2026-01-01T00:00:00.000Z", modified_at: "2026-01-01T00:00:00.000Z", manual_edits: 0 },
            stream_id: "s-2",
        });

        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(onCardsBatch).toHaveBeenCalledTimes(1);
        expect(onCardsBatch.mock.calls[0][0][0].card_id).toBe("card-1");
        actor.stop();
    });

    it("maps done into workflow.completed before closing stream", async () => {
        const fake = new FakeEventSource();
        const onDomainEvent = vi.fn();
        const onConnectionState = vi.fn();
        const machine = createStreamActorMachine({
            getStreamUrl: () => "http://localhost/stream?workflow_id=wf-1",
            createEventSource: () => fake,
            nowIso: () => "2026-01-01T00:00:00.000Z",
            onConnectionState,
            onStreamError: vi.fn(),
            onDomainEvent,
            onCardsBatch: vi.fn(),
            onRejectWireEvent: vi.fn(),
        });

        const actor = createActor(machine);
        actor.start();
        actor.send({ type: "START", workflowId: "wf-1", restartKey: 0 });
        fake.emitOpen();

        fake.emit("done", {
            type: "done",
            workflow_id: "wf-1",
            stream_id: "done-1",
            result: { ok: true },
        });

        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(onDomainEvent).toHaveBeenCalledTimes(1);
        expect(onDomainEvent.mock.calls[0][0]).toMatchObject({
            kind: "workflow.completed",
            workflowId: "wf-1",
        });
        expect(onConnectionState).toHaveBeenCalledWith("idle");
        actor.stop();
    });

    it("reports terminal reconnect failure exactly once", async () => {
        vi.useFakeTimers();
        let actor: ReturnType<typeof createActor> | null = null;
        try {
            const onConnectionState = vi.fn();
            const onStreamError = vi.fn();
            const machine = createStreamActorMachine({
                getStreamUrl: () => "http://localhost/stream?workflow_id=wf-1",
                createEventSource: () => new FakeEventSource(),
                nowIso: () => "2026-01-01T00:00:00.000Z",
                onConnectionState,
                onStreamError,
                onDomainEvent: vi.fn(),
                onCardsBatch: vi.fn(),
                onRejectWireEvent: vi.fn(),
            });

            actor = createActor(machine);
            actor.start();
            actor.send({ type: "START", workflowId: "wf-1", restartKey: 0 });
            actor.send({ type: "OPEN" });
            expect(actor.getSnapshot().value).toBe("connected");

            for (let attempt = 1; attempt <= 9; attempt += 1) {
                actor.send({ type: "ERROR", reason: "transport_error" });
                await vi.runOnlyPendingTimersAsync();
                if (attempt <= 8) {
                    actor.send({ type: "OPEN" });
                    expect(actor.getSnapshot().value).toBe("connected");
                }
            }

            expect(actor.getSnapshot().value).toBe("failure");
            expect(onConnectionState.mock.calls.filter(([state]) => state === "error")).toHaveLength(1);
            expect(
                onStreamError.mock.calls.filter(
                    ([message]) => message === "Stream unavailable for workflow wf-1 after 9 attempts",
                ),
            ).toHaveLength(1);
        } finally {
            actor?.stop();
            vi.useRealTimers();
        }
    });
});

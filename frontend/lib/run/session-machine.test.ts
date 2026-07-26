import { createActor } from "xstate";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createSessionMachine } from "./session-machine";
import type { RuntimeEnvelope } from "./runtime-envelope";

vi.mock("@microsoft/fetch-event-source", () => ({ fetchEventSource: vi.fn(() => new Promise(() => undefined)) }));

let sequence = 0;
const envelope = (event_type: string, payload: Record<string, unknown>, run_id = "run-1"): RuntimeEnvelope => ({
    schema_version: "agentos.conversation.v1",
    event_id: `event-${++sequence}`,
    thread_id: "thread-1",
    run_id,
    process_id: "process-1",
    sequence,
    event_type,
    occurred_at: "2026-07-25T00:00:00Z",
    payload,
});

const start = () => {
    const actor = createActor(createSessionMachine("thread-1"), { input: "thread-1" });
    actor.start();
    actor.send({ type: "START_WORKFLOW", workflowId: "process-1", runId: "run-1", query: "question" });
    return actor;
};

describe("conversation session machine", () => {
    beforeEach(() => { sequence = 0; });

    it("shows the user message immediately without an empty assistant placeholder", () => {
        const actor = start();
        actor.send({ type: "SSE_ENVELOPE", envelope: envelope("RUN_STARTED", {}) });
        expect(actor.getSnapshot().context.status).toBe("running");
        expect(actor.getSnapshot().context.messages).toMatchObject([{ role: "user", content: "question" }]);
        expect(actor.getSnapshot().context.messages.some((message) => message.isGenerating)).toBe(false);
        expect(actor.getSnapshot().context.streamingOverlay).toEqual({});
        actor.stop();
    });

    it("keeps deltas in an overlay and promotes TEXT_MESSAGE_END to persisted messages", () => {
        const actor = start();
        actor.send({ type: "SSE_ENVELOPE", envelope: envelope("RUN_STARTED", {}) });
        actor.send({ type: "SSE_ENVELOPE", envelope: envelope("TEXT_MESSAGE_START", { message_id: "assistant-1", role: "assistant" }) });
        expect(actor.getSnapshot().context.messages).toHaveLength(1);
        actor.send({ type: "SSE_ENVELOPE", envelope: envelope("TEXT_MESSAGE_CONTENT", { message_id: "assistant-1", delta: "hel" }) });
        actor.send({ type: "SSE_ENVELOPE", envelope: envelope("TEXT_MESSAGE_CONTENT", { message_id: "assistant-1", delta: "lo" }) });
        expect(actor.getSnapshot().context.streamingOverlay["assistant-1"].content).toBe("hello");
        expect(actor.getSnapshot().context.persistedMessages).toHaveLength(1);

        actor.send({ type: "SSE_ENVELOPE", envelope: envelope("TEXT_MESSAGE_END", { message_id: "assistant-1", role: "assistant", content: "hello" }) });
        const context = actor.getSnapshot().context;
        expect(context.streamingOverlay).toEqual({});
        expect(context.persistedMessages.at(-1)).toMatchObject({ id: "assistant-1", content: "hello" });
        expect(context.persistedMessages.at(-1)?.isStreaming).not.toBe(true);
        actor.stop();
    });

    it("persists the clarification prompt before ending the run as interrupt", () => {
        const actor = start();
        actor.send({ type: "SSE_ENVELOPE", envelope: envelope("RUN_STARTED", {}) });
        actor.send({ type: "SSE_ENVELOPE", envelope: envelope("TEXT_MESSAGE_CONTENT", { message_id: "assistant-1", delta: "Which scope?" }) });
        actor.send({ type: "SSE_ENVELOPE", envelope: envelope("TEXT_MESSAGE_END", { message_id: "assistant-1", content: "Which scope?" }) });
        actor.send({ type: "SSE_ENVELOPE", envelope: envelope("RUN_FINISHED", {
            outcome: "interrupt",
            interrupt: { interrupt_id: "interrupt-1", type: "user_input", prompt: "Which scope?" },
        }) });
        const context = actor.getSnapshot().context;
        expect(context.status).toBe("waiting_input");
        expect(context.interrupt?.interrupt_id).toBe("interrupt-1");
        expect(context.messages.at(-1)?.content).toBe("Which scope?");
        expect(context.streamingOverlay).toEqual({});
        actor.stop();
    });

    it("never lets extension events create messages or finish a run", () => {
        const actor = start();
        actor.send({ type: "SSE_ENVELOPE", envelope: envelope("PLANNER_TRACE", { message: "trace" }) });
        actor.send({ type: "SSE_ENVELOPE", envelope: envelope("kardcraft.node.completed", { message: "done" }) });
        expect(actor.getSnapshot().context.status).toBe("running");
        expect(actor.getSnapshot().context.messages).toHaveLength(1);
        actor.stop();
    });

    it("ignores duplicate and out-of-order thread sequences", () => {
        const actor = start();
        const delta = envelope("TEXT_MESSAGE_CONTENT", { message_id: "assistant-1", delta: "once" });
        actor.send({ type: "SSE_ENVELOPE", envelope: delta });
        actor.send({ type: "SSE_ENVELOPE", envelope: delta });
        actor.send({ type: "SSE_ENVELOPE", envelope: { ...delta, event_id: "older", sequence: delta.sequence - 1 } });
        expect(actor.getSnapshot().context.streamingOverlay["assistant-1"].content).toBe("once");
        actor.stop();
    });

    it("clears the run overlay on errors", () => {
        const actor = start();
        actor.send({ type: "SSE_ENVELOPE", envelope: envelope("TEXT_MESSAGE_CONTENT", { message_id: "assistant-1", delta: "partial" }) });
        actor.send({ type: "SSE_ENVELOPE", envelope: envelope("RUN_ERROR", { code: "FAILED", message: "boom" }) });
        expect(actor.getSnapshot().context.status).toBe("failed");
        expect(actor.getSnapshot().context.streamingOverlay).toEqual({});
        expect(actor.getSnapshot().context.messages.some((message) => message.content === "partial")).toBe(false);
        actor.stop();
    });

    it("replaces local state with a cursor-consistent snapshot", () => {
        const actor = start();
        actor.send({
            type: "HYDRATE",
            workflowId: "process-1",
            runId: "run-1",
            messages: [{ id: "server-user", role: "user", content: "question", runId: "run-1" }],
            events: [],
            cards: [],
            cursor: 42,
            state: { conversation_status: "running" },
        });
        expect(actor.getSnapshot().context.lastEventID).toBe(42);
        expect(actor.getSnapshot().context.messages.map((message) => message.id)).toEqual(["server-user"]);
        actor.stop();
    });
});

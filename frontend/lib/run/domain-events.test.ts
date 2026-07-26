import { describe, expect, it } from "vitest";
import { mapWireEventToDomainEvent } from "./domain-events";

const map = (eventType: string, payload: Record<string, unknown> = {}) => mapWireEventToDomainEvent({
    eventType,
    payload: { run_id: "run-1", ...payload },
    fallbackWorkflowId: "process-1",
    fallbackSessionId: "thread-1",
    at: "2026-07-25T00:00:00Z",
    eventId: "event-1",
    sequence: 1,
});

describe("agentos.conversation.v1 domain mapping", () => {
    it("maps the six canonical lifecycle event types", () => {
        expect(map("RUN_STARTED")).toMatchObject({ ok: true, event: { kind: "workflow.started", runId: "run-1" } });
        expect(map("TEXT_MESSAGE_START", { message_id: "message-1", role: "assistant" }))
            .toMatchObject({ ok: true, event: { kind: "message.started", messageId: "message-1" } });
        expect(map("TEXT_MESSAGE_CONTENT", { message_id: "message-1", delta: "hello" }))
            .toMatchObject({ ok: true, event: { kind: "message.delta", delta: "hello" } });
        expect(map("TEXT_MESSAGE_END", { message_id: "message-1", content: "hello" }))
            .toMatchObject({ ok: true, event: { kind: "message.completed", content: "hello" } });
        expect(map("RUN_FINISHED", { outcome: "normal" }))
            .toMatchObject({ ok: true, event: { kind: "run.finished", outcome: "normal" } });
        expect(map("RUN_ERROR", { code: "FAILED", message: "boom" }))
            .toMatchObject({ ok: true, event: { kind: "workflow.failed", reasonCode: "FAILED", message: "boom" } });
    });

    it("keeps namespaced extensions in the timeline channel", () => {
        expect(map("kardcraft.node.started", { message: "Planner started" }))
            .toMatchObject({ ok: true, event: { kind: "timeline.event", eventKind: "kardcraft.node.started" } });
    });

    it("rejects malformed canonical events", () => {
        expect(map("TEXT_MESSAGE_CONTENT", { message_id: "message-1" })).toMatchObject({ ok: false });
        expect(map("RUN_FINISHED", { outcome: "unknown" })).toMatchObject({ ok: false });
    });
});

import { describe, expect, it } from "vitest";
import { mapWireEventToDomainEvent, projectDomainEventToRunEvent } from "./domain-events";

describe("run domain event mapper", () => {
    it("maps WORKFLOW_STARTED to workflow.started", () => {
        const mapped = mapWireEventToDomainEvent({
            eventType: "WORKFLOW_STARTED",
            payload: {
                workflow_id: "wf-1",
            },
            fallbackWorkflowId: "wf-1",
            at: "2026-04-21T00:00:00.000Z",
            eventId: "evt-1",
        });

        expect(mapped.ok).toBe(true);
        if (!mapped.ok) return;
        expect(mapped.event.kind).toBe("workflow.started");
        expect(mapped.event.workflowId).toBe("wf-1");
    });

    it("maps thread.message.completed to message.completed and projects back to run event", () => {
        const mapped = mapWireEventToDomainEvent({
            eventType: "thread.message.completed",
            payload: {
                workflow_id: "wf-2",
                stream_id: "msg-1",
                content: {
                    text: "hello",
                },
                metadata: {
                    provider: "openai",
                },
            },
            fallbackWorkflowId: "wf-2",
            at: "2026-04-21T00:00:00.000Z",
            eventId: "evt-2",
        });

        expect(mapped.ok).toBe(true);
        if (!mapped.ok) return;
        expect(mapped.event.kind).toBe("message.completed");

        const projected = projectDomainEventToRunEvent(mapped.event);
        expect(projected).not.toBeNull();
        expect(projected?.type).toBe("thread.message.completed");
    });

    it("maps workflow.paused to control.pause.confirmed", () => {
        const mapped = mapWireEventToDomainEvent({
            eventType: "workflow.paused",
            payload: {
                workflow_id: "wf-3",
            },
            fallbackWorkflowId: "wf-3",
            at: "2026-04-21T00:00:00.000Z",
            eventId: "evt-3",
        });

        expect(mapped.ok).toBe(true);
        if (!mapped.ok) return;
        expect(mapped.event.kind).toBe("control.pause.confirmed");
        expect(mapped.event.taskId).toBe("wf-3");
    });

    it("rejects unknown wire event types", () => {
        const mapped = mapWireEventToDomainEvent({
            eventType: "SOME_UNKNOWN_EVENT",
            payload: {
                workflow_id: "wf-4",
            },
            fallbackWorkflowId: "wf-4",
            at: "2026-04-21T00:00:00.000Z",
            eventId: "evt-4",
        });

        expect(mapped.ok).toBe(false);
        if (mapped.ok) return;
        expect(mapped.reason).toBe("unknown_type");
    });
});

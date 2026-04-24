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

    it("maps workflow.pausing/workflow.cancelling to control requested events", () => {
        const pausingMapped = mapWireEventToDomainEvent({
            eventType: "workflow.pausing",
            payload: {
                workflow_id: "wf-request-1",
            },
            fallbackWorkflowId: "wf-request-1",
            at: "2026-04-21T00:00:00.000Z",
            eventId: "evt-request-1",
        });
        expect(pausingMapped.ok).toBe(true);
        if (!pausingMapped.ok) return;
        expect(pausingMapped.event.kind).toBe("control.pause.requested");

        const pausingProjected = projectDomainEventToRunEvent(pausingMapped.event);
        expect(pausingProjected?.type).toBe("workflow.pausing");

        const cancellingMapped = mapWireEventToDomainEvent({
            eventType: "workflow.cancelling",
            payload: {
                workflow_id: "wf-request-2",
            },
            fallbackWorkflowId: "wf-request-2",
            at: "2026-04-21T00:00:00.000Z",
            eventId: "evt-request-2",
        });
        expect(cancellingMapped.ok).toBe(true);
        if (!cancellingMapped.ok) return;
        expect(cancellingMapped.event.kind).toBe("control.cancel.requested");

        const cancellingProjected = projectDomainEventToRunEvent(cancellingMapped.event);
        expect(cancellingProjected?.type).toBe("workflow.cancelling");
    });

    it("maps workflow.cancelled to control.cancel.confirmed and projects back", () => {
        const mapped = mapWireEventToDomainEvent({
            eventType: "workflow.cancelled",
            payload: {
                workflow_id: "wf-5",
            },
            fallbackWorkflowId: "wf-5",
            at: "2026-04-21T00:00:00.000Z",
            eventId: "evt-5",
        });

        expect(mapped.ok).toBe(true);
        if (!mapped.ok) return;
        expect(mapped.event.kind).toBe("control.cancel.confirmed");
        expect(mapped.event.taskId).toBe("wf-5");

        const projected = projectDomainEventToRunEvent(mapped.event);
        expect(projected?.type).toBe("workflow.cancelled");
        expect(projected?.workflow_id).toBe("wf-5");
    });

    it("maps WORKFLOW_CANCELLED alias to control.cancel.confirmed", () => {
        const mapped = mapWireEventToDomainEvent({
            eventType: "WORKFLOW_CANCELLED",
            payload: {
                workflow_id: "wf-6",
            },
            fallbackWorkflowId: "wf-6",
            at: "2026-04-21T00:00:00.000Z",
            eventId: "evt-6",
        });

        expect(mapped.ok).toBe(true);
        if (!mapped.ok) return;
        expect(mapped.event.kind).toBe("control.cancel.confirmed");
        expect(mapped.event.taskId).toBe("wf-6");
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

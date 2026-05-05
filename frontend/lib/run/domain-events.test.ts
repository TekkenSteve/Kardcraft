import { describe, expect, it } from "vitest";
import { mapWireEventToDomainEvent, projectDomainEventToRunEvent } from "./domain-events";

describe("run domain event mapper", () => {
    it("maps WORKFLOW_STARTED to workflow.started", () => {
        const mapped = mapWireEventToDomainEvent({
            eventType: "WORKFLOW_STARTED",
            payload: {
                workflow_id: "wf-1",
                run_id: "run-1",
            },
            fallbackWorkflowId: "wf-1",
            at: "2026-04-21T00:00:00.000Z",
            eventId: "evt-1",
        });

        expect(mapped.ok).toBe(true);
        if (!mapped.ok) return;
        expect(mapped.event.kind).toBe("workflow.started");
        expect(mapped.event.workflowId).toBe("wf-1");
        expect(mapped.event.runId).toBe("run-1");

        const projected = projectDomainEventToRunEvent(mapped.event);
        expect(projected?.type).toBe("WORKFLOW_STARTED");
        expect(projected?.run_id).toBe("run-1");
    });

    it("maps thread.message.completed to message.completed and projects back to run event", () => {
        const mapped = mapWireEventToDomainEvent({
            eventType: "thread.message.completed",
            payload: {
                workflow_id: "wf-2",
                run_id: "run-2",
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

    it("keeps terminal workflow payload on completed events and treats done as stream end only", () => {
        const completed = mapWireEventToDomainEvent({
            eventType: "WORKFLOW_COMPLETED",
            payload: {
                workflow_id: "wf-terminal",
                run_id: "run-terminal",
                message: "Generated 3 flashcards",
                final_cards: [{ id: "c1", front: "Q", back: "A" }],
            },
            fallbackWorkflowId: "wf-terminal",
            at: "2026-04-21T00:00:00.000Z",
            eventId: "evt-terminal",
        });
        expect(completed.ok).toBe(true);
        if (!completed.ok) return;
        expect(completed.event.kind).toBe("workflow.completed");
        expect(completed.event.result).toMatchObject({
            message: "Generated 3 flashcards",
            final_cards: [{ id: "c1", front: "Q", back: "A" }],
        });

        const done = mapWireEventToDomainEvent({
            eventType: "done",
            payload: {
                workflow_id: "wf-terminal",
                run_id: "run-terminal",
                message: "Stream end",
            },
            fallbackWorkflowId: "wf-terminal",
            at: "2026-04-21T00:00:01.000Z",
            eventId: "evt-done",
        });
        expect(done.ok).toBe(true);
        if (!done.ok) return;
        expect(done.event.kind).toBe("timeline.event");
        expect(done.event.eventKind).toBe("done");
    });

    it("keeps workflow.paused as a timeline record instead of control state", () => {
        const mapped = mapWireEventToDomainEvent({
            eventType: "workflow.paused",
            payload: {
                workflow_id: "wf-3",
                run_id: "run-3",
            },
            fallbackWorkflowId: "wf-3",
            at: "2026-04-21T00:00:00.000Z",
            eventId: "evt-3",
        });

        expect(mapped.ok).toBe(true);
        if (!mapped.ok) return;
        expect(mapped.event.kind).toBe("timeline.event");
        expect(mapped.event.eventKind).toBe("workflow.paused");
    });

    it("keeps node lifecycle payload fields for timeline pairing", () => {
        const mapped = mapWireEventToDomainEvent({
            eventType: "NODE_COMPLETED",
            payload: {
                workflow_id: "wf-node",
                run_id: "run-node",
                stream_id: "node-2",
                node_name: "card_scope_planner",
                event_name: "card_scope_planner",
                message: "card_scope_planner completed",
            },
            fallbackWorkflowId: "wf-node",
            at: "2026-04-21T00:00:00.000Z",
            eventId: "evt-node-2",
        });

        expect(mapped.ok).toBe(true);
        if (!mapped.ok) return;
        expect(mapped.event.kind).toBe("timeline.event");

        const projected = projectDomainEventToRunEvent(mapped.event);
        expect(projected?.type).toBe("NODE_COMPLETED");
        expect(projected?.run_id).toBe("run-node");
        expect(projected?.payload).toMatchObject({
            node_name: "card_scope_planner",
            event_name: "card_scope_planner",
        });
    });

    it("maps LLM usage runtime records into the timeline channel", () => {
        const mapped = mapWireEventToDomainEvent({
            eventType: "LLM_USAGE_RECORDED",
            payload: {
                workflow_id: "wf-usage",
                run_id: "run-usage",
                usage: {
                    model: "gpt-test",
                    total_tokens: 42,
                },
            },
            fallbackWorkflowId: "wf-usage",
            at: "2026-04-21T00:00:00.000Z",
            eventId: "evt-usage",
        });

        expect(mapped.ok).toBe(true);
        if (!mapped.ok) return;
        expect(mapped.event.kind).toBe("timeline.event");
        expect(mapped.event.eventKind).toBe("LLM_USAGE_RECORDED");

        const projected = projectDomainEventToRunEvent(mapped.event);
        expect(projected?.type).toBe("LLM_USAGE_RECORDED");
        expect(projected?.payload).toMatchObject({
            usage: {
                model: "gpt-test",
            },
        });
    });

    it("keeps workflow control progress records in the timeline channel", () => {
        const pausingMapped = mapWireEventToDomainEvent({
            eventType: "workflow.pausing",
            payload: {
                workflow_id: "wf-request-1",
                run_id: "run-request-1",
            },
            fallbackWorkflowId: "wf-request-1",
            at: "2026-04-21T00:00:00.000Z",
            eventId: "evt-request-1",
        });
        expect(pausingMapped.ok).toBe(true);
        if (!pausingMapped.ok) return;
        expect(pausingMapped.event.kind).toBe("timeline.event");

        const pausingProjected = projectDomainEventToRunEvent(pausingMapped.event);
        expect(pausingProjected?.type).toBe("workflow.pausing");

        const cancellingMapped = mapWireEventToDomainEvent({
            eventType: "workflow.cancelling",
            payload: {
                workflow_id: "wf-request-2",
                run_id: "run-request-2",
            },
            fallbackWorkflowId: "wf-request-2",
            at: "2026-04-21T00:00:00.000Z",
            eventId: "evt-request-2",
        });
        expect(cancellingMapped.ok).toBe(true);
        if (!cancellingMapped.ok) return;
        expect(cancellingMapped.event.kind).toBe("timeline.event");

        const cancellingProjected = projectDomainEventToRunEvent(cancellingMapped.event);
        expect(cancellingProjected?.type).toBe("workflow.cancelling");
    });

    it("maps workflow.cancelled to control.cancel.confirmed and projects back", () => {
        const mapped = mapWireEventToDomainEvent({
            eventType: "workflow.cancelled",
            payload: {
                workflow_id: "wf-5",
                run_id: "run-5",
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
                run_id: "run-6",
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

    it("keeps future runtime events visible as timeline records", () => {
        const mapped = mapWireEventToDomainEvent({
            eventType: "SOME_FUTURE_EVENT",
            payload: {
                workflow_id: "wf-4",
                run_id: "run-4",
                message: "future event happened",
            },
            fallbackWorkflowId: "wf-4",
            at: "2026-04-21T00:00:00.000Z",
            eventId: "evt-4",
        });

        expect(mapped.ok).toBe(true);
        if (!mapped.ok) return;
        expect(mapped.event.kind).toBe("timeline.event");
        expect(mapped.event.eventKind).toBe("SOME_FUTURE_EVENT");
        expect(mapped.event.message).toBe("future event happened");
    });

    it("rejects events missing run_id", () => {
        const mapped = mapWireEventToDomainEvent({
            eventType: "WORKFLOW_STARTED",
            payload: {
                workflow_id: "wf-missing-run",
            },
            fallbackWorkflowId: "wf-missing-run",
            at: "2026-04-21T00:00:00.000Z",
            eventId: "evt-missing-run",
        });

        expect(mapped.ok).toBe(false);
        if (mapped.ok) return;
        expect(mapped.reason).toBe("invalid_payload");
    });
});

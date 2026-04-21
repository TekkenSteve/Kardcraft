import { describe, expect, it } from "vitest";
import { createActor } from "xstate";
import { createSessionMachine } from "./session-machine";

describe("session machine transitions", () => {
    it("matches declarative lifecycle model paths", async () => {
        const actor = createActor(createSessionMachine());
        actor.start();

        const modelPath = [
            { type: "OPEN_SESSION", expected: "hydrating", payload: { sessionId: "s1" } },
            { type: "REHYDRATE_DONE", expected: "ready", payload: { hasActiveWorkflow: false } },
            { type: "CREATE_TASK", expected: "running", payload: { workflowId: "wf-1", taskId: "wf-1" } },
        ] as const;

        for (const step of modelPath) {
            actor.send({ type: step.type, ...(step.payload as object) });
            expect(actor.getSnapshot().value).toBe(step.expected);
        }

        actor.send({
            type: "DOMAIN_EVENT",
            event: {
                kind: "workflow.completed",
                workflowId: "wf-1",
                sessionId: "s1",
                at: "2026-01-01T00:00:00Z",
                result: "ok",
            },
        });
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(actor.getSnapshot().value).toEqual({ terminal: "completed" });
        actor.stop();
    });

    it("follows lifecycle from hydrate to completed terminal", async () => {
        const actor = createActor(createSessionMachine());
        actor.start();

        actor.send({ type: "OPEN_SESSION", sessionId: "s1" });
        expect(actor.getSnapshot().value).toBe("hydrating");

        actor.send({ type: "REHYDRATE_DONE", hasActiveWorkflow: false });
        expect(actor.getSnapshot().value).toBe("ready");

        actor.send({ type: "CREATE_TASK", workflowId: "wf-1", taskId: "wf-1" });
        expect(actor.getSnapshot().value).toBe("running");

        actor.send({
            type: "DOMAIN_EVENT",
            event: {
                kind: "workflow.completed",
                workflowId: "wf-1",
                sessionId: "s1",
                at: "2026-01-01T00:00:00Z",
                result: "ok",
            },
        });
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(actor.getSnapshot().value).toEqual({ terminal: "completed" });
        actor.stop();
    });

    it("handles pause-resume-cancel control flow", () => {
        const actor = createActor(createSessionMachine());
        actor.start();

        actor.send({ type: "OPEN_SESSION", sessionId: "s1" });
        actor.send({ type: "REHYDRATE_DONE", hasActiveWorkflow: true, workflowId: "wf-1", taskId: "wf-1" });
        expect(actor.getSnapshot().value).toBe("running");

        actor.send({
            type: "DOMAIN_EVENT",
            event: {
                kind: "control.pause.confirmed",
                sessionId: "s1",
                taskId: "wf-1",
                at: "2026-01-01T00:00:00Z",
            },
        });
        expect(actor.getSnapshot().value).toBe("paused");

        actor.send({
            type: "DOMAIN_EVENT",
            event: {
                kind: "control.resume.confirmed",
                sessionId: "s1",
                taskId: "wf-1",
                at: "2026-01-01T00:00:01Z",
            },
        });
        expect(actor.getSnapshot().value).toBe("running");

        actor.send({
            type: "DOMAIN_EVENT",
            event: {
                kind: "control.cancel.confirmed",
                sessionId: "s1",
                taskId: "wf-1",
                at: "2026-01-01T00:00:02Z",
            },
        });
        expect(actor.getSnapshot().value).toEqual({ terminal: "cancelled" });
        actor.stop();
    });

    it("captures typed control rejection as deterministic error channel", () => {
        const actor = createActor(createSessionMachine());
        actor.start();
        actor.send({ type: "OPEN_SESSION", sessionId: "s1" });
        actor.send({ type: "REHYDRATE_DONE", hasActiveWorkflow: true, workflowId: "wf-1", taskId: "wf-1" });

        actor.send({
            type: "DOMAIN_EVENT",
            event: {
                kind: "control.rejected",
                sessionId: "s1",
                taskId: "wf-1",
                code: "invalid-transition",
                message: "invalid transition",
                at: "2026-01-01T00:00:02Z",
            },
        });

        expect(actor.getSnapshot().value).toBe("running");
        expect(actor.getSnapshot().context.lastError).toEqual({
            code: "INVALID_TRANSITION",
            message: "invalid transition",
        });
        actor.stop();
    });
});

describe("session machine impossible transitions", () => {
    it("keeps state unchanged when RESUME is emitted outside paused state", () => {
        const actor = createActor(createSessionMachine());
        actor.start();

        actor.send({ type: "OPEN_SESSION", sessionId: "s1" });
        actor.send({ type: "REHYDRATE_DONE", hasActiveWorkflow: true, workflowId: "wf-1", taskId: "wf-1" });
        expect(actor.getSnapshot().value).toBe("running");

        actor.send({
            type: "DOMAIN_EVENT",
            event: {
                kind: "control.resume.confirmed",
                sessionId: "s1",
                taskId: "wf-1",
                at: "2026-01-01T00:00:00Z",
            },
        });

        expect(actor.getSnapshot().value).toBe("running");
        actor.stop();
    });

    it("does not leave terminal state on non-RESET events", async () => {
        const actor = createActor(createSessionMachine());
        actor.start();
        actor.send({ type: "OPEN_SESSION", sessionId: "s1" });
        actor.send({ type: "REHYDRATE_DONE", hasActiveWorkflow: true, workflowId: "wf-1", taskId: "wf-1" });

        actor.send({
            type: "DOMAIN_EVENT",
            event: {
                kind: "workflow.failed",
                workflowId: "wf-1",
                sessionId: "s1",
                at: "2026-01-01T00:00:00Z",
                reasonCode: "INTERNAL",
                message: "boom",
            },
        });
        expect(actor.getSnapshot().value).toEqual({ terminal: "failed" });

        actor.send({ type: "CREATE_TASK", workflowId: "wf-2", taskId: "wf-2" });
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(actor.getSnapshot().value).toEqual({ terminal: "failed" });

        actor.send({ type: "RESET" });
        expect(actor.getSnapshot().value).toBe("idle");
        actor.stop();
    });
});

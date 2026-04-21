import { describe, expect, it } from "vitest";
import { createActor } from "xstate";
import { createSessionRegistryMachine } from "./session-registry-machine";
import { createDraftSessionId } from "./types";

describe("session registry machine", () => {
    it("creates and activates session on ACTIVATE_SESSION", () => {
        const actor = createActor(createSessionRegistryMachine());
        actor.start();

        actor.send({ type: "ACTIVATE_SESSION", sessionId: "s1" });

        const snapshot = actor.getSnapshot();
        expect(snapshot.context.activeSessionKey).toBe("session:s1");
        expect(snapshot.context.sessions["session:s1"]?.sessionId).toBe("s1");
        actor.stop();
    });

    it("promotes draft session to real session id", () => {
        const actor = createActor(createSessionRegistryMachine());
        actor.start();
        const draftSessionId = createDraftSessionId();

        actor.send({ type: "ACTIVATE_SESSION", sessionId: draftSessionId });
        actor.send({
            type: "ADD_MESSAGE",
            sessionId: draftSessionId,
            message: {
                id: "m1",
                role: "user",
                content: "hello",
            },
        });
        actor.send({
            type: "ADD_EVENT",
            sessionId: draftSessionId,
            event: {
                id: 1,
                type: "WORKFLOW_STARTED",
                workflow_id: "wf-1",
                stream_id: "stream-1",
            },
        });

        actor.send({ type: "PROMOTE_SESSION", fromSessionId: draftSessionId, toSessionId: "s99" });

        const snapshot = actor.getSnapshot();
        expect(snapshot.context.sessions[draftSessionId]).toBeUndefined();
        expect(snapshot.context.sessions["session:s99"]?.messages).toHaveLength(1);
        expect(snapshot.context.sessions["session:s99"]?.events).toHaveLength(1);
        expect(snapshot.context.sessions["session:s99"]?.mainWorkflowId).toBeNull();
        expect(snapshot.context.sessions["session:s99"]?.sessionId).toBe("s99");
        expect(snapshot.context.activeSessionKey).toBe("session:s99");
        actor.stop();
    });

    it("deduplicates events by stream id and workflow id", () => {
        const actor = createActor(createSessionRegistryMachine());
        actor.start();

        actor.send({ type: "ACTIVATE_SESSION", sessionId: "s1" });
        actor.send({
            type: "ADD_EVENT",
            sessionId: "s1",
            event: {
                id: 1,
                type: "TOOL_OBSERVATION",
                stream_id: "st-1",
                workflow_id: "wf-1",
            },
        });
        actor.send({
            type: "ADD_EVENT",
            sessionId: "s1",
            event: {
                id: 2,
                type: "TOOL_OBSERVATION",
                stream_id: "st-1",
                workflow_id: "wf-1",
            },
        });

        const snapshot = actor.getSnapshot();
        expect(snapshot.context.sessions["session:s1"]?.events).toHaveLength(1);
        actor.stop();
    });

    it("preserves full draft session state across promotion", () => {
        const actor = createActor(createSessionRegistryMachine());
        actor.start();
        const draftSessionId = createDraftSessionId();

        actor.send({ type: "ACTIVATE_SESSION", sessionId: draftSessionId });
        actor.send({ type: "SET_STATUS", sessionId: draftSessionId, status: "running" });
        actor.send({ type: "SET_RUN_PHASE", sessionId: draftSessionId, phase: "streaming" });
        actor.send({
            type: "SET_CARDS",
            sessionId: draftSessionId,
            cards: [{
                id: "c1",
                user_id: "u1",
                card_id: "c1",
                content: { version: 1, model: "mcq", data: { front: "Q", back: "A" }, media: [] },
                edit_state: { status: "draft" },
                concepts: [],
                meta: { created_at: "2026-01-01T00:00:00Z", modified_at: "2026-01-01T00:00:00Z", manual_edits: 0 },
            }],
        });
        actor.send({
            type: "ADD_MESSAGE",
            sessionId: draftSessionId,
            message: { id: "m1", role: "assistant", content: "hello" },
        });
        actor.send({
            type: "PROMOTE_SESSION",
            fromSessionId: draftSessionId,
            toSessionId: "s-real",
        });

        const snapshot = actor.getSnapshot();
        const promoted = snapshot.context.sessions["session:s-real"];
        expect(promoted).toBeDefined();
        expect(promoted?.status).toBe("running");
        expect(promoted?.runPhase).toBe("streaming");
        expect(promoted?.cards).toHaveLength(1);
        expect(promoted?.messages).toHaveLength(1);
        expect(promoted?.sessionId).toBe("s-real");
        actor.stop();
    });

    it("isolates two simultaneous sessions with independent state", () => {
        const actor = createActor(createSessionRegistryMachine());
        actor.start();

        actor.send({ type: "ACTIVATE_SESSION", sessionId: "s1" });
        actor.send({ type: "ADD_MESSAGE", sessionId: "s1", message: { id: "m1", role: "assistant", content: "a" } });
        actor.send({ type: "SET_STATUS", sessionId: "s1", status: "running" });

        actor.send({ type: "ACTIVATE_SESSION", sessionId: "s2" });
        actor.send({ type: "ADD_MESSAGE", sessionId: "s2", message: { id: "m2", role: "assistant", content: "b" } });
        actor.send({ type: "SET_STATUS", sessionId: "s2", status: "completed" });

        const snapshot = actor.getSnapshot();
        expect(snapshot.context.sessions["session:s1"]?.messages).toHaveLength(1);
        expect(snapshot.context.sessions["session:s1"]?.status).toBe("running");
        expect(snapshot.context.sessions["session:s2"]?.messages).toHaveLength(1);
        expect(snapshot.context.sessions["session:s2"]?.status).toBe("completed");
        actor.stop();
    });

    it("does not mutate inactive session when rapidly switching active session", () => {
        const actor = createActor(createSessionRegistryMachine());
        actor.start();

        actor.send({ type: "ACTIVATE_SESSION", sessionId: "sA" });
        actor.send({ type: "ADD_MESSAGE", sessionId: "sA", message: { id: "mA", role: "assistant", content: "alpha" } });

        actor.send({ type: "ACTIVATE_SESSION", sessionId: "sB" });
        actor.send({ type: "ADD_MESSAGE", sessionId: "sB", message: { id: "mB", role: "assistant", content: "beta" } });

        actor.send({ type: "ACTIVATE_SESSION", sessionId: "sA" });
        actor.send({ type: "SET_STREAM_ERROR", sessionId: "sA", error: "a-error" });

        const snapshot = actor.getSnapshot();
        expect(snapshot.context.activeSessionKey).toBe("session:sA");
        expect(snapshot.context.sessions["session:sA"]?.streamError).toBe("a-error");
        expect(snapshot.context.sessions["session:sB"]?.streamError).toBeNull();
        expect(snapshot.context.sessions["session:sB"]?.messages).toHaveLength(1);
        actor.stop();
    });
});

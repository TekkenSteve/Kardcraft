import { describe, expect, it } from "vitest";
import { createActor } from "xstate";
import { createSessionRegistryMachine } from "./session-registry-machine";
import { createSessionBundleLoaderMachine, type SessionBundleLoadResult } from "./session-bundle-loader-machine";
import { toSessionKey } from "./types";
import { createRadarStore } from "../radar/store";
import { applyWorkflowPausedTransition, applyWorkflowTerminalTransition } from "../../components/radar/radar-workflow-transitions";

const tick = async () => new Promise((resolve) => setTimeout(resolve, 0));

describe("run system critical flows (e2e)", () => {
    it("preserves runtime state across draft-to-real session promotion", () => {
        const actor = createActor(createSessionRegistryMachine());
        actor.start();

        const draftSessionId = "draft:123";
        const realSessionId = "session_real_123";

        actor.send({ type: "ACTIVATE_SESSION", sessionId: draftSessionId });
        actor.send({ type: "SET_STATUS", sessionId: draftSessionId, status: "running" });
        actor.send({ type: "SET_RUN_PHASE", sessionId: draftSessionId, phase: "streaming" });
        actor.send({
            type: "ADD_MESSAGE",
            sessionId: draftSessionId,
            message: {
                id: "user-1",
                role: "user",
                content: "Generate cards",
                timestamp: "10:00:00",
            },
        });
        actor.send({
            type: "ADD_MESSAGE",
            sessionId: draftSessionId,
            message: {
                id: "generating-1",
                role: "assistant",
                content: "Generating...",
                timestamp: "10:00:01",
                isGenerating: true,
            },
        });

        actor.send({ type: "PROMOTE_SESSION", fromSessionId: draftSessionId, toSessionId: realSessionId });

        const snapshot = actor.getSnapshot().context;
        const promoted = snapshot.sessions[toSessionKey(realSessionId)];

        expect(promoted).toBeDefined();
        expect(promoted?.sessionId).toBe(realSessionId);
        expect(promoted?.status).toBe("running");
        expect(promoted?.runPhase).toBe("streaming");
        expect(promoted?.messages).toHaveLength(2);
        expect(promoted?.messages[1]?.isGenerating).toBe(true);
        expect(snapshot.activeSessionKey).toBe(toSessionKey(realSessionId));

        actor.stop();
    });

    it("keeps latest session load authoritative during rapid route switches", async () => {
        const pending = new Map<string, (value: SessionBundleLoadResult) => void>();

        const loader = createActor(
            createSessionBundleLoaderMachine({
                loadBundle: async (sessionId: string) =>
                    await new Promise<SessionBundleLoadResult>((resolve) => {
                        pending.set(sessionId, resolve);
                    }),
            }),
        );
        loader.start();

        loader.send({ type: "SYNC_SESSION", sessionId: "session_A" });
        expect(loader.getSnapshot().value).toBe("loading");

        loader.send({ type: "SYNC_SESSION", sessionId: "session_B" });
        expect(loader.getSnapshot().value).toBe("loading");

        pending.get("session_A")?.({
            session: { session_id: "session_A" },
            conversation: { session_id: "session_A", messages: [] },
            timeline: { session_id: "session_A", events: [] },
            history: { session_id: "session_A", tasks: [] },
        });
        await tick();
        expect(loader.getSnapshot().value).toBe("loading");

        pending.get("session_B")?.({
            session: { session_id: "session_B" },
            conversation: {
                session_id: "session_B",
                messages: [{ id: "m-1", role: "assistant", content: "ready" }],
            },
            timeline: {
                session_id: "session_B",
                events: [{ type: "STATUS_UPDATE", message: "ok" }],
            },
            history: { session_id: "session_B", tasks: [{ task_id: "workflow_B" }] },
        });
        await tick();

        const snapshot = loader.getSnapshot();
        expect(snapshot.value).toBe("success");
        expect(snapshot.context.data?.session.session_id).toBe("session_B");
        expect(snapshot.context.data?.conversation.messages).toHaveLength(1);

        loader.stop();
    });

    it("scenario A: pausing a running workflow closes the loop and blocks radar progress", () => {
        const actor = createActor(createSessionRegistryMachine());
        actor.start();

        const sessionId = "session_pause_1";
        const workflowId = "workflow_pause_1";
        actor.send({ type: "ACTIVATE_SESSION", sessionId });
        actor.send({ type: "SET_MAIN_WORKFLOW_ID", sessionId, workflowId });
        actor.send({ type: "SET_STATUS", sessionId, status: "running" });
        actor.send({ type: "SET_RUN_PHASE", sessionId, phase: "streaming" });
        actor.send({
            type: "ADD_MESSAGE",
            sessionId,
            message: {
                id: `generating-${workflowId}`,
                role: "assistant",
                content: "Generating...",
                taskId: workflowId,
                isGenerating: true,
            },
        });
        actor.send({
            type: "ADD_MESSAGE",
            sessionId,
            message: {
                id: `status-control-pausing-${workflowId}`,
                role: "status",
                content: "Pausing workflow...",
                taskId: workflowId,
            },
        });

        // pause confirmed closed-loop
        actor.send({ type: "CLEAR_GENERATING_MESSAGES", sessionId, taskId: workflowId });
        actor.send({ type: "CLEAR_STATUS_MESSAGES", sessionId, taskId: workflowId });
        actor.send({ type: "SET_PAUSED", sessionId, paused: true });
        actor.send({ type: "SET_CANCELLING", sessionId, value: false });
        actor.send({ type: "SET_STATUS", sessionId, status: "paused" });
        actor.send({ type: "SET_RUN_PHASE", sessionId, phase: "hydrated" });
        actor.send({ type: "SET_STREAM_ERROR", sessionId, error: null });
        actor.send({
            type: "UPSERT_MESSAGE",
            sessionId,
            message: {
                id: `assistant-control-paused-${workflowId}`,
                role: "assistant",
                content: "Execution paused.",
                taskId: workflowId,
            },
        });

        const pausedSession = actor.getSnapshot().context.sessions[toSessionKey(sessionId)];
        expect(pausedSession?.status).toBe("paused");
        expect(pausedSession?.runPhase).toBe("hydrated");
        expect(pausedSession?.messages.some((message) => message.isGenerating)).toBe(false);
        expect(pausedSession?.messages.some((message) => message.id === `assistant-control-paused-${workflowId}`)).toBe(true);

        const radarStore = createRadarStore();
        radarStore.getState().applyTick({
            tick_id: 1,
            items: [
                {
                    id: `${workflowId}::agent-main`,
                    group: "A",
                    sector: "PLANNING",
                    depends_on: [],
                    estimate_ms: 3000,
                    status: "in_progress",
                    tps_min: 1,
                    tps_max: 1,
                    tps: 1,
                    tokens_done: 1,
                    est_tokens: 2,
                },
                {
                    id: "other_workflow::agent-other",
                    group: "A",
                    sector: "PLANNING",
                    depends_on: [],
                    estimate_ms: 3000,
                    status: "in_progress",
                    tps_min: 1,
                    tps_max: 1,
                    tps: 1,
                    tokens_done: 1,
                    est_tokens: 2,
                },
            ],
        });

        applyWorkflowPausedTransition(radarStore, workflowId, 1);
        const pausedItem = radarStore.getState().items[`${workflowId}::agent-main`];
        const otherItem = radarStore.getState().items["other_workflow::agent-other"];
        expect(pausedItem?.status).toBe("blocked");
        expect(otherItem?.status).toBe("in_progress");

        actor.stop();
    });

    it("scenario B: cancelling a running workflow closes the loop and clears radar in-progress items", () => {
        const actor = createActor(createSessionRegistryMachine());
        actor.start();

        const sessionId = "session_cancel_1";
        const workflowId = "workflow_cancel_1";
        actor.send({ type: "ACTIVATE_SESSION", sessionId });
        actor.send({ type: "SET_MAIN_WORKFLOW_ID", sessionId, workflowId });
        actor.send({ type: "SET_STATUS", sessionId, status: "running" });
        actor.send({ type: "SET_RUN_PHASE", sessionId, phase: "streaming" });
        actor.send({ type: "SET_CANCELLING", sessionId, value: true });
        actor.send({
            type: "ADD_MESSAGE",
            sessionId,
            message: {
                id: `generating-${workflowId}`,
                role: "assistant",
                content: "Generating...",
                taskId: workflowId,
                isGenerating: true,
            },
        });

        // cancel confirmed closed-loop
        actor.send({ type: "CLEAR_GENERATING_MESSAGES", sessionId, taskId: workflowId });
        actor.send({ type: "CLEAR_STATUS_MESSAGES", sessionId, taskId: workflowId });
        actor.send({ type: "SET_PAUSED", sessionId, paused: false });
        actor.send({ type: "SET_CANCELLED", sessionId, value: true });
        actor.send({ type: "SET_RUN_PHASE", sessionId, phase: "hydrated" });
        actor.send({ type: "SET_STREAM_ERROR", sessionId, error: null });
        actor.send({
            type: "UPSERT_MESSAGE",
            sessionId,
            message: {
                id: `assistant-control-cancelled-${workflowId}`,
                role: "assistant",
                content: "Execution cancelled.",
                taskId: workflowId,
                isCancelled: true,
            },
        });

        const cancelledSession = actor.getSnapshot().context.sessions[toSessionKey(sessionId)];
        expect(cancelledSession?.status).toBe("cancelled");
        expect(cancelledSession?.isCancelled).toBe(true);
        expect(cancelledSession?.runPhase).toBe("hydrated");
        expect(cancelledSession?.messages.some((message) => message.isGenerating)).toBe(false);
        expect(cancelledSession?.messages.some((message) => message.id === `assistant-control-cancelled-${workflowId}`)).toBe(true);

        const radarStore = createRadarStore();
        radarStore.getState().applyTick({
            tick_id: 1,
            items: [
                {
                    id: `${workflowId}::agent-main`,
                    group: "A",
                    sector: "PLANNING",
                    depends_on: [],
                    estimate_ms: 3000,
                    status: "in_progress",
                    tps_min: 1,
                    tps_max: 1,
                    tps: 1,
                    tokens_done: 1,
                    est_tokens: 2,
                },
            ],
            agents: [{ id: `${workflowId}::agent-main`, work_item_id: `${workflowId}::agent-main`, x: 0, y: 0, v: 0.1, curve_phase: 0 }],
        });

        const timeoutRefs = new Map<string, number>();
        applyWorkflowTerminalTransition(radarStore, workflowId, 1, {
            schedule: (callback) => {
                callback();
                return 1;
            },
            clear: () => {},
            timeoutRefs,
        });

        const items = Object.values(radarStore.getState().items);
        expect(items.some((item) => item.status === "in_progress")).toBe(false);

        actor.stop();
    });
});

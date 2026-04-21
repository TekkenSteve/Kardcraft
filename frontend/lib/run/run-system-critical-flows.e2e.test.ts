import { describe, expect, it } from "vitest";
import { createActor } from "xstate";
import { createSessionRegistryMachine } from "./session-registry-machine";
import { createSessionBundleLoaderMachine, type SessionBundleLoadResult } from "./session-bundle-loader-machine";
import { toSessionKey } from "./types";

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
});

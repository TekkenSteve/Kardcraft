import { describe, expect, it, vi } from "vitest";
import { createActor } from "xstate";
import { createSessionBundleLoaderMachine, SessionBundleLoadResult } from "./session-bundle-loader-machine";

const buildBundle = (sessionId: string): SessionBundleLoadResult => ({
    session: {
        session_id: sessionId,
        user_id: "u1",
        task_count: 0,
        tokens_used: 0,
        created_at: "2026-01-01T00:00:00Z",
    },
    conversation: {
        session_id: sessionId,
        messages: [],
    },
    timeline: {
        session_id: sessionId,
        events: [],
    },
    history: {
        session_id: sessionId,
        tasks: [],
    },
});

describe("session bundle loader machine", () => {
    it("loads bundle on session sync", async () => {
        const loadBundle = vi.fn(async (sessionId: string) => buildBundle(sessionId));
        const machine = createSessionBundleLoaderMachine({ loadBundle });
        const actor = createActor(machine);
        actor.start();

        actor.send({ type: "SYNC_SESSION", sessionId: "s1" });
        await new Promise((resolve) => setTimeout(resolve, 0));

        const snapshot = actor.getSnapshot();
        expect(snapshot.value).toBe("success");
        expect(snapshot.context.data?.session.session_id).toBe("s1");
        expect(loadBundle).toHaveBeenCalledWith("s1");
        actor.stop();
    });

    it("enters failure on loader error and supports retry", async () => {
        const loadBundle = vi
            .fn()
            .mockRejectedValueOnce(new Error("boom"))
            .mockResolvedValueOnce(buildBundle("s2"));
        const machine = createSessionBundleLoaderMachine({ loadBundle });
        const actor = createActor(machine);
        actor.start();

        actor.send({ type: "SYNC_SESSION", sessionId: "s2" });
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(actor.getSnapshot().value).toBe("failure");
        expect(actor.getSnapshot().context.error).toBe("boom");

        actor.send({ type: "RETRY" });
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(actor.getSnapshot().value).toBe("success");
        expect(actor.getSnapshot().context.data?.session.session_id).toBe("s2");
        actor.stop();
    });

    it("keeps loading when session switches during in-flight load", async () => {
        let releaseFirstLoad: (() => void) | null = null;
        let releaseSecondLoad: (() => void) | null = null;
        const loadBundle = vi
            .fn()
            .mockImplementationOnce(
                () =>
                    new Promise<SessionBundleLoadResult>((resolve) => {
                        releaseFirstLoad = () => resolve(buildBundle("s1"));
                    }),
            )
            .mockImplementationOnce(
                () =>
                    new Promise<SessionBundleLoadResult>((resolve) => {
                        releaseSecondLoad = () => resolve(buildBundle("s2"));
                    }),
            );

        const machine = createSessionBundleLoaderMachine({ loadBundle });
        const actor = createActor(machine);
        actor.start();

        actor.send({ type: "SYNC_SESSION", sessionId: "s1" });
        actor.send({ type: "SYNC_SESSION", sessionId: "s2" });
        await new Promise((resolve) => setTimeout(resolve, 0));

        expect(actor.getSnapshot().value).toBe("loading");
        expect(actor.getSnapshot().context.sessionId).toBe("s2");
        expect(loadBundle).toHaveBeenNthCalledWith(1, "s1");
        expect(loadBundle).toHaveBeenNthCalledWith(2, "s2");

        releaseFirstLoad?.();
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(actor.getSnapshot().value).toBe("loading");

        releaseSecondLoad?.();
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(actor.getSnapshot().value).toBe("success");
        expect(actor.getSnapshot().context.data?.session.session_id).toBe("s2");
        actor.stop();
    });
});

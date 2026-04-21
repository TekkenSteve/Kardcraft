import { describe, expect, it, vi } from "vitest";
import { createActor } from "xstate";
import { createWorkspaceLoaderMachine, inferWorkspacePhaseFromData, WorkspaceLoadResult } from "./workspace-loader-machine";

const buildWorkspace = (sessionId: string, cardCount: number, projectionStatus?: "hydrated" | "empty"): WorkspaceLoadResult => ({
    sessionId,
    cards: Array.from({ length: cardCount }, (_, index) => ({
        id: `c-${index}`,
        user_id: "u1",
        card_id: `c-${index}`,
        content: {
            version: 1,
            model: "mcq",
            data: {
                front: "Q",
                back: "A",
            },
            media: [],
        },
        edit_state: {
            status: "draft",
        },
        concepts: [],
        meta: {
            created_at: "2026-01-01T00:00:00Z",
            modified_at: "2026-01-01T00:00:00Z",
            manual_edits: 0,
        },
    })),
    projectionStatus,
    templateId: "tpl-1",
    supportedQuestionTypes: ["mcq", "cloze"],
});

describe("workspace loader machine", () => {
    it("loads workspace on session sync", async () => {
        const loadWorkspace = vi.fn(async (sessionId: string) => buildWorkspace(sessionId, 2, "hydrated"));
        const machine = createWorkspaceLoaderMachine({ loadWorkspace });
        const actor = createActor(machine);
        actor.start();

        actor.send({ type: "SYNC_SESSION", sessionId: "s1" });
        await new Promise((resolve) => setTimeout(resolve, 0));

        const snapshot = actor.getSnapshot();
        expect(snapshot.value).toBe("success");
        expect(snapshot.context.data?.sessionId).toBe("s1");
        expect(snapshot.context.data?.cards).toHaveLength(2);
        expect(loadWorkspace).toHaveBeenCalledWith("s1");
        actor.stop();
    });

    it("supports refresh in success state", async () => {
        const loadWorkspace = vi
            .fn()
            .mockResolvedValueOnce(buildWorkspace("s1", 0, "empty"))
            .mockResolvedValueOnce(buildWorkspace("s1", 3, "hydrated"));

        const machine = createWorkspaceLoaderMachine({ loadWorkspace });
        const actor = createActor(machine);
        actor.start();

        actor.send({ type: "SYNC_SESSION", sessionId: "s1" });
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(actor.getSnapshot().context.data?.cards).toHaveLength(0);

        actor.send({ type: "REFRESH" });
        await new Promise((resolve) => setTimeout(resolve, 0));

        expect(actor.getSnapshot().value).toBe("success");
        expect(actor.getSnapshot().context.data?.cards).toHaveLength(3);
        expect(loadWorkspace).toHaveBeenCalledTimes(2);
        actor.stop();
    });

    it("enters failure and can retry", async () => {
        const loadWorkspace = vi
            .fn()
            .mockRejectedValueOnce(new Error("workspace boom"))
            .mockResolvedValueOnce(buildWorkspace("s2", 1, "hydrated"));

        const machine = createWorkspaceLoaderMachine({ loadWorkspace });
        const actor = createActor(machine);
        actor.start();

        actor.send({ type: "SYNC_SESSION", sessionId: "s2" });
        await new Promise((resolve) => setTimeout(resolve, 0));

        expect(actor.getSnapshot().value).toBe("failure");
        expect(actor.getSnapshot().context.error).toBe("workspace boom");

        actor.send({ type: "RETRY" });
        await new Promise((resolve) => setTimeout(resolve, 0));

        expect(actor.getSnapshot().value).toBe("success");
        expect(actor.getSnapshot().context.data?.cards).toHaveLength(1);
        actor.stop();
    });
});

describe("inferWorkspacePhaseFromData", () => {
    it("returns empty for null payload", () => {
        expect(inferWorkspacePhaseFromData(null)).toBe("empty");
    });

    it("prefers explicit projection status", () => {
        expect(inferWorkspacePhaseFromData(buildWorkspace("s1", 5, "empty"))).toBe("empty");
        expect(inferWorkspacePhaseFromData(buildWorkspace("s1", 0, "hydrated"))).toBe("hydrated");
    });

    it("infers from card count when projection status missing", () => {
        expect(inferWorkspacePhaseFromData(buildWorkspace("s1", 0))).toBe("empty");
        expect(inferWorkspacePhaseFromData(buildWorkspace("s1", 2))).toBe("hydrated");
    });
});

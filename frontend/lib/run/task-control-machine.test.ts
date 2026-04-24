import { describe, expect, it } from "vitest";
import { createActor } from "xstate";
import { taskControlMachine } from "./task-control-machine";

describe("task control machine", () => {
    it("enables control when task is running and not blocked", () => {
        const actor = createActor(taskControlMachine);
        actor.start();
        actor.send({
            type: "SYNC_INPUT",
            currentTaskId: "t-1",
            runStatus: "running",
            isCancelling: false,
        });

        expect(actor.getSnapshot().context.canControlTask).toBe(true);
        actor.stop();
    });

    it("keeps control enabled when task is paused", () => {
        const actor = createActor(taskControlMachine);
        actor.start();
        actor.send({
            type: "SYNC_INPUT",
            currentTaskId: "t-1",
            runStatus: "paused",
            isCancelling: false,
        });

        expect(actor.getSnapshot().context.canControlTask).toBe(true);
        actor.stop();
    });

    it("blocks current task after cancellation is confirmed", () => {
        const actor = createActor(taskControlMachine);
        actor.start();
        actor.send({
            type: "SYNC_INPUT",
            currentTaskId: "t-1",
            runStatus: "running",
            isCancelling: false,
        });
        actor.send({
            type: "CONTROL_STATE_UPDATED",
            cancelled: true,
        });

        const { blockedTaskId, canControlTask } = actor.getSnapshot().context;
        expect(blockedTaskId).toBe("t-1");
        expect(canControlTask).toBe(false);
        actor.stop();
    });

    it("clears task block when switching to another task", () => {
        const actor = createActor(taskControlMachine);
        actor.start();
        actor.send({
            type: "SYNC_INPUT",
            currentTaskId: "t-1",
            runStatus: "running",
            isCancelling: false,
        });
        actor.send({
            type: "CONTROL_REQUEST_FAILED",
            blockCurrentTask: true,
        });
        actor.send({
            type: "SYNC_INPUT",
            currentTaskId: "t-2",
            runStatus: "running",
            isCancelling: false,
        });

        const { blockedTaskId, canControlTask } = actor.getSnapshot().context;
        expect(blockedTaskId).toBeNull();
        expect(canControlTask).toBe(true);
        actor.stop();
    });

    it("resets pause/resume loading flags after control state update", () => {
        const actor = createActor(taskControlMachine);
        actor.start();
        actor.send({
            type: "SYNC_INPUT",
            currentTaskId: "t-1",
            runStatus: "running",
            isCancelling: false,
        });
        actor.send({ type: "PAUSE_REQUESTED" });
        actor.send({
            type: "CONTROL_STATE_UPDATED",
            cancelled: false,
        });

        const state = actor.getSnapshot().context;
        expect(state.isPauseLoading).toBe(false);
        expect(state.isResumeLoading).toBe(false);
        actor.stop();
    });
});

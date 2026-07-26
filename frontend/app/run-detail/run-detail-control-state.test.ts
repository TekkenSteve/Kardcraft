import { describe, expect, it } from "vitest";
import { deriveRunDetailControlState } from "./run-detail-control-state";

describe("deriveRunDetailControlState", () => {
    it("derives control visibility matrix from run status", () => {
        expect(deriveRunDetailControlState("running")).toMatchObject({
            isControlSessionActive: true,
            showPause: true,
            showResume: false,
            showCancel: true,
            isPauseLoading: false,
            isResumeLoading: false,
            inputDisabled: true,
        });
        expect(deriveRunDetailControlState("waiting_input")).toMatchObject({
            isControlSessionActive: true,
            showPause: false,
            showResume: false,
            showCancel: true,
            inputDisabled: false,
        });
        expect(deriveRunDetailControlState("pausing")).toMatchObject({
            isControlSessionActive: true,
            showPause: true,
            showResume: false,
            showCancel: true,
            isPauseLoading: true,
            isResumeLoading: false,
            inputDisabled: true,
        });
        expect(deriveRunDetailControlState("paused")).toMatchObject({
            isControlSessionActive: true,
            showPause: false,
            showResume: true,
            showCancel: true,
            isPauseLoading: false,
            isResumeLoading: false,
            inputDisabled: true,
        });
        expect(deriveRunDetailControlState("paused")).toMatchObject({
            isControlSessionActive: true,
            showPause: false,
            showResume: true,
            showCancel: true,
            isPauseLoading: false,
            isResumeLoading: false,
            inputDisabled: true,
        });
        expect(deriveRunDetailControlState("resuming")).toMatchObject({
            isControlSessionActive: true,
            showPause: false,
            showResume: true,
            showCancel: true,
            isPauseLoading: false,
            isResumeLoading: true,
            inputDisabled: true,
        });
        expect(deriveRunDetailControlState("cancelling")).toMatchObject({
            isControlSessionActive: true,
            showPause: false,
            showResume: false,
            showCancel: true,
            isPauseLoading: false,
            isResumeLoading: false,
            inputDisabled: true,
        });
        expect(deriveRunDetailControlState("completed")).toMatchObject({
            isControlSessionActive: false,
            showPause: false,
            showResume: false,
            showCancel: false,
            inputDisabled: false,
        });
        expect(deriveRunDetailControlState("failed")).toMatchObject({
            isControlSessionActive: false,
            showPause: false,
            showResume: false,
            showCancel: false,
            inputDisabled: false,
        });
        expect(deriveRunDetailControlState("cancelled")).toMatchObject({
            isControlSessionActive: false,
            showPause: false,
            showResume: false,
            showCancel: false,
            inputDisabled: false,
        });
    });
});

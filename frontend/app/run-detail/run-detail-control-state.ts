import { RunStatus } from "@/lib/run/types";

export type RunDetailControlState = {
    isControlSessionActive: boolean;
    isPauseLoading: boolean;
    isResumeLoading: boolean;
    showPause: boolean;
    showResume: boolean;
    showCancel: boolean;
    inputDisabled: boolean;
};

export function deriveRunDetailControlState(status: RunStatus): RunDetailControlState {
    const isControlSessionActive =
        status === "running" ||
        status === "pausing" ||
        status === "paused" ||
        status === "resuming" ||
        status === "cancelling";

    const isPauseLoading = status === "pausing";
    const isResumeLoading = status === "resuming";

    return {
        isControlSessionActive,
        isPauseLoading,
        isResumeLoading,
        showPause: status === "running" || status === "pausing",
        showResume: status === "paused" || status === "resuming",
        showCancel: status === "running" || status === "pausing" || status === "paused" || status === "resuming" || status === "cancelling",
        inputDisabled: isControlSessionActive,
    };
}

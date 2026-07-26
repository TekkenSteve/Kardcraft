import { describe, expect, it } from "vitest";
import type { RunEvent } from "@/lib/kardcraft/types";
import { deriveProcessProgress } from "./process-progress";

const event = (type: RunEvent["type"], runId: string, payload: Record<string, unknown>): RunEvent => ({
    type,
    workflow_id: "process-1",
    run_id: runId,
    payload,
} as RunEvent);

describe("deriveProcessProgress", () => {
    it("returns the latest node lifecycle state for the current run", () => {
        const events = [
            event("NODE_STARTED", "run-1", { node_name: "syllabus_supervisor" }),
            event("NODE_COMPLETED", "run-1", { node_name: "syllabus_supervisor" }),
            event("NODE_STARTED", "run-1", { node_name: "card_generator" }),
        ];

        expect(deriveProcessProgress(events, "run-1")).toEqual({
            label: "Card Generator",
            status: "running",
        });
    });

    it("does not leak progress from an earlier run", () => {
        const events = [
            event("NODE_STARTED", "run-1", { node_name: "old_node" }),
            event("WORKFLOW_PROGRESS", "run-2", { message: "Preparing the next step" }),
        ];

        expect(deriveProcessProgress(events, "run-2")).toEqual({
            label: "Preparing the next step",
            status: "running",
        });
    });

    it("ignores diagnostics and message lifecycle events", () => {
        const events = [
            event("PLANNER_TRACE" as RunEvent["type"], "run-1", { message: "trace" }),
            event("thread.message.delta", "run-1", { delta: "hello" }),
        ];

        expect(deriveProcessProgress(events, "run-1")).toBeNull();
    });
});

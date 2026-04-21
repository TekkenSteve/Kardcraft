import { describe, expect, it } from "vitest";
import { parseTaskStatus } from "./api";

describe("task status parser", () => {
    it("maps backend task status literals to normalized status", () => {
        expect(parseTaskStatus("TASK_STATUS_QUEUED")).toBe("queued");
        expect(parseTaskStatus("TASK_STATUS_RUNNING")).toBe("running");
        expect(parseTaskStatus("TASK_STATUS_COMPLETED")).toBe("completed");
        expect(parseTaskStatus("TASK_STATUS_FAILED")).toBe("failed");
        expect(parseTaskStatus("TASK_STATUS_CANCELLED")).toBe("cancelled");
    });

    it("accepts normalized status literals", () => {
        expect(parseTaskStatus("queued")).toBe("queued");
        expect(parseTaskStatus("running")).toBe("running");
        expect(parseTaskStatus("completed")).toBe("completed");
        expect(parseTaskStatus("failed")).toBe("failed");
        expect(parseTaskStatus("cancelled")).toBe("cancelled");
    });

    it("rejects unknown status values", () => {
        expect(() => parseTaskStatus("TASK_STATUS_PENDING_REVIEW")).toThrow("Invalid task status");
        expect(() => parseTaskStatus(123)).toThrow("Invalid task status");
    });
});

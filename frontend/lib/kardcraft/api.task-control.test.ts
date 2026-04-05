import { beforeEach, describe, expect, it, vi } from "vitest";
import { cancelTask, pauseTask, resumeTask } from "./api";

describe("task control api contract", () => {
    const fetchMock = vi.fn();

    beforeEach(() => {
        fetchMock.mockReset();
        vi.stubGlobal("fetch", fetchMock);
    });

    it("sends Idempotency-Key header for pause", async () => {
        fetchMock.mockResolvedValue(new Response(
            JSON.stringify({ success: true, message: "ok", workflow_id: "t1" }),
            { status: 200, headers: { "Content-Type": "application/json" } }
        ));

        await pauseTask("t1");

        expect(fetchMock).toHaveBeenCalledTimes(1);
        const [url, init] = fetchMock.mock.calls[0];
        expect(url).toBe("/api/v1/tasks/t1/pause");
        expect(init.method).toBe("POST");
        expect(init.credentials).toBe("include");
        expect(init.headers["Idempotency-Key"]).toBeTypeOf("string");
        expect(init.headers["Idempotency-Key"].length).toBeGreaterThan(0);
    });

    it("maps invalid-transition error envelope to rich error message", async () => {
        fetchMock.mockResolvedValue(
            new Response(
                JSON.stringify({
                    error: {
                        code: "invalid-transition",
                        message: "task is not paused",
                    },
                }),
                { status: 409, headers: { "Content-Type": "application/json" } }
            )
        );

        await expect(resumeTask("t1")).rejects.toThrow("invalid-transition");
    });

    it("maps authz-denied error envelope to rich error message", async () => {
        fetchMock.mockResolvedValue(
            new Response(
                JSON.stringify({
                    error: {
                        code: "authz-denied",
                        message: "access denied for task resource",
                    },
                }),
                { status: 403, headers: { "Content-Type": "application/json" } }
            )
        );

        await expect(cancelTask("t1")).rejects.toThrow("authz-denied");
    });
});

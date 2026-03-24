import { beforeEach, describe, expect, it, vi } from "vitest";
import { cancelSessionTask, pauseSessionTask, resumeSessionTask } from "./api";

describe("session control api contract", () => {
    const fetchMock = vi.fn();

    beforeEach(() => {
        fetchMock.mockReset();
        vi.stubGlobal("fetch", fetchMock);
    });

    it("sends Idempotency-Key header for pause", async () => {
        fetchMock.mockResolvedValue(
            new Response(
                JSON.stringify({
                    session_id: "s1",
                    active_task_id: "t1",
                    task_state: "PAUSED",
                    session_control_state: "ACTIVE_PAUSED",
                    version: 2,
                    result: "applied",
                }),
                { status: 200, headers: { "Content-Type": "application/json" } }
            )
        );

        await pauseSessionTask("s1");

        expect(fetchMock).toHaveBeenCalledTimes(1);
        const [url, init] = fetchMock.mock.calls[0];
        expect(url).toBe("/api/v1/sessions/s1/pause");
        expect(init.method).toBe("POST");
        expect(init.credentials).toBe("include");
        expect(init.headers["Idempotency-Key"]).toBeTypeOf("string");
        expect(init.headers["Idempotency-Key"].length).toBeGreaterThan(0);
    });

    it("maps no-active-task error envelope to rich error message", async () => {
        fetchMock.mockResolvedValue(
            new Response(
                JSON.stringify({
                    error: {
                        code: "no-active-task",
                        message: "session has no active task",
                    },
                }),
                { status: 404, headers: { "Content-Type": "application/json" } }
            )
        );

        await expect(resumeSessionTask("s1")).rejects.toThrow("no-active-task");
    });

    it("maps authz-denied error envelope to rich error message", async () => {
        fetchMock.mockResolvedValue(
            new Response(
                JSON.stringify({
                    error: {
                        code: "authz-denied",
                        message: "access denied for session resource",
                    },
                }),
                { status: 403, headers: { "Content-Type": "application/json" } }
            )
        );

        await expect(cancelSessionTask("s1")).rejects.toThrow("authz-denied");
    });
});


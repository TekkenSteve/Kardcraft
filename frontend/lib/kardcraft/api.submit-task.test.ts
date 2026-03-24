import { beforeEach, describe, expect, it, vi } from "vitest";
import { submitTask } from "./api";

describe("submitTask error mapping", () => {
    const fetchMock = vi.fn();

    beforeEach(() => {
        fetchMock.mockReset();
        vi.stubGlobal("fetch", fetchMock);
    });

    it("maps active-task-exists error envelope to rich error message", async () => {
        fetchMock.mockResolvedValue(
            new Response(
                JSON.stringify({
                    error: {
                        code: "active-task-exists",
                        message: "session already has an active task",
                        details: {
                            session_id: "s1",
                            active_task_id: "t1",
                        },
                    },
                }),
                { status: 409, headers: { "Content-Type": "application/json" } }
            )
        );

        await expect(
            submitTask({
                query: "hello",
                task_type: "main",
                context: { template_id: "tpl-1" },
                session_id: "s1",
            })
        ).rejects.toThrow("active-task-exists");
    });
});


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

    it("submits main card generation template through input.context", async () => {
        fetchMock.mockResolvedValue(
            new Response(
                JSON.stringify({
                    workflow_id: "wf-main",
                    status: "running",
                    created_at: "2026-05-05T00:00:00Z",
                }),
                { status: 201, headers: { "Content-Type": "application/json" } }
            )
        );

        await submitTask({
            query: "hello",
            task_type: "main",
            context: { template_id: "tpl-main", template_version: 2 },
            session_id: "s1",
        });

        const body = JSON.parse(String(fetchMock.mock.calls[0][1].body));
        expect(body.input.template_id).toBeUndefined();
        expect(body.input.context).toMatchObject({
            template_id: "tpl-main",
            template_version: 2,
        });
    });

    it("submits card template workflow template through input.template_id", async () => {
        fetchMock.mockResolvedValue(
            new Response(
                JSON.stringify({
                    workflow_id: "wf-template",
                    status: "running",
                    created_at: "2026-05-05T00:00:00Z",
                }),
                { status: 201, headers: { "Content-Type": "application/json" } }
            )
        );

        await submitTask({
            query: "refine this template",
            task_type: "card_template",
            template_id: "tpl-source",
            context: { template_id: "tpl-context", render_target: "anki" },
            session_id: "s1",
        });

        const body = JSON.parse(String(fetchMock.mock.calls[0][1].body));
        expect(body.input.context).toBeUndefined();
        expect(body.input.template_id).toBe("tpl-source");
        expect(body.input.variables).toMatchObject({
            template_id: "tpl-context",
            render_target: "anki",
        });
    });
});

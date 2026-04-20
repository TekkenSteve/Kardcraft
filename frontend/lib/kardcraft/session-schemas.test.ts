import { describe, expect, it } from "vitest";
import {
    SessionHistoryResponseSchema,
    SessionStateResponseSchema,
    SessionTimelineResponseSchema,
    SessionWorkspaceResponseSchema,
} from "./session-schemas";

describe("session schema projection status", () => {
    it("accepts timeline projection_status", () => {
        const parsed = SessionTimelineResponseSchema.parse({
            session_id: "s1",
            events: [],
            projection_status: "empty",
        });
        expect(parsed.projection_status).toBe("empty");
    });

    it("accepts workspace projection_status with hydrated cards", () => {
        const parsed = SessionWorkspaceResponseSchema.parse({
            session_id: "s1",
            version: 1,
            status: "active",
            card_count: 1,
            projection_status: "hydrated",
            cards: [
                {
                    id: "c1",
                    user_id: "u1",
                    card_id: "c1",
                    content: {
                        version: 1,
                        model: "mcq",
                        data: { front: "f", back: "b", tags: [], concepts: [] },
                        media: [],
                    },
                    edit_state: { status: "draft" },
                    concepts: [],
                    meta: {
                        created_at: "2026-03-18T00:00:00Z",
                        modified_at: "2026-03-18T00:00:00Z",
                        manual_edits: 0,
                    },
                },
            ],
        });
        expect(parsed.projection_status).toBe("hydrated");
        expect(parsed.cards).toHaveLength(1);
    });
});

describe("session history usage metadata schema", () => {
    it("accepts zero-usage task payload", () => {
        const parsed = SessionHistoryResponseSchema.parse({
            session_id: "s1",
            tasks: [
                {
                    task_id: "t1",
                    workflow_id: "t1",
                    model_used: "openai/gpt-4o-mini",
                    provider: "openai",
                    total_tokens: 0,
                    total_cost_usd: 0,
                    usage_projection_status: "partial",
                    usage_projection_reason: "awaiting_usage_projection",
                },
            ],
        });
        expect(parsed.tasks[0].total_tokens).toBe(0);
        expect(parsed.tasks[0].usage_projection_status).toBe("partial");
        expect(parsed.tasks[0].model_used).toBe("openai/gpt-4o-mini");
    });

    it("accepts multi-model breakdown with estimated quality marker", () => {
        const parsed = SessionHistoryResponseSchema.parse({
            session_id: "s2",
            tasks: [
                {
                    task_id: "t2",
                    workflow_id: "t2",
                    total_tokens: 420,
                    total_cost_usd: 0.042,
                    metadata: {
                        model_breakdown: [
                            {
                                model: "openai/gpt-4o-mini",
                                provider: "openai",
                                executions: 2,
                                tokens: 220,
                                cost_usd: 0.02,
                                prompt_tokens: 150,
                                completion_tokens: 70,
                                estimated_executions: 0,
                            },
                            {
                                model: "anthropic/claude-3-5-sonnet",
                                provider: "anthropic",
                                executions: 1,
                                tokens: 200,
                                cost_usd: 0.022,
                                prompt_tokens: 120,
                                completion_tokens: 80,
                                estimated_executions: 1,
                            },
                        ],
                        usage_quality: {
                            has_estimated_usage: true,
                            estimated_ratio: 0.33,
                        },
                    },
                    usage_projection_status: "finalized",
                    usage_projection_reason: "usage_ingested",
                },
            ],
        });
        expect(parsed.tasks[0].metadata?.model_breakdown).toHaveLength(2);
        expect(parsed.tasks[0].metadata?.usage_quality?.has_estimated_usage).toBe(true);
        expect(parsed.tasks[0].usage_projection_status).toBe("finalized");
    });
});

describe("session state contract schema", () => {
    it("accepts extended control-plane fields", () => {
        const parsed = SessionStateResponseSchema.parse({
            session_id: "s1",
            status: "running",
            active_task_id: "t1",
            task_state: "RUNNING",
            session_control_state: "ACTIVE_RUNNING",
            version: 3,
            updated_at: "2026-03-21T00:00:00Z",
        });
        expect(parsed.task_state).toBe("RUNNING");
        expect(parsed.session_control_state).toBe("ACTIVE_RUNNING");
        expect(parsed.version).toBe(3);
    });
});

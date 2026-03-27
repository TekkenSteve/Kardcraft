import { z } from "zod";

export const SessionSchema = z.object({
    session_id: z.string(),
    user_id: z.string(),
    title: z.string().nullable().optional(),
    pinned: z.boolean().optional(),
    task_count: z.number(),
    tokens_used: z.number(),
    token_budget: z.number().optional(),
    created_at: z.string(),
    updated_at: z.string().optional(),
    expires_at: z.string().optional(),
    context: z.record(z.string(), z.unknown()).optional(),
    last_activity_at: z.string().optional(),
    is_active: z.boolean().optional(),
    successful_tasks: z.number().optional(),
    failed_tasks: z.number().optional(),
    success_rate: z.number().optional(),
    total_cost_usd: z.number().optional(),
    average_cost_per_task: z.number().optional(),
    budget_utilization: z.number().optional(),
    budget_remaining: z.number().optional(),
    is_near_budget_limit: z.boolean().optional(),
    latest_task_query: z.string().optional(),
    latest_task_status: z.string().optional(),
    is_research_session: z.boolean().optional(),
    first_task_mode: z.string().optional(),
    research_strategy: z.string().optional(),
});

export const SessionListResponseSchema = z.object({
    sessions: z.array(SessionSchema),
    total_count: z.number(),
});

export const ConversationMessageSchema = z.object({
    id: z.string(),
    role: z.enum(["user", "assistant", "system"]),
    content: z.string(),
    timestamp: z.string().optional(),
    task_id: z.string().optional(),
    metadata: z.record(z.string(), z.unknown()).optional(),
});

export const SessionConversationResponseSchema = z.object({
    session_id: z.string(),
    messages: z.array(ConversationMessageSchema),
});

export const TimelineEventSchema = z.object({
    id: z.number(),
    type: z.string(),
    message: z.string().optional(),
    timestamp: z.string().optional(),
    workflow_id: z.string().optional(),
    task_id: z.string().optional(),
    stream_id: z.string().optional(),
    payload: z.unknown().optional(),
});

export const SessionTimelineResponseSchema = z.object({
    session_id: z.string(),
    events: z.array(TimelineEventSchema),
    projection_status: z.enum(["hydrated", "empty"]).optional(),
});

export const SessionHistoryTaskSchema = z.object({
    task_id: z.string(),
    workflow_id: z.string(),
    query: z.string().optional(),
    status: z.string().optional(),
    mode: z.string().optional(),
    error_message: z.string().optional(),
    total_tokens: z.number().optional(),
    total_cost_usd: z.number().optional(),
    metadata: z
        .object({
            model: z.string().optional(),
            provider: z.string().optional(),
            model_breakdown: z
                .array(
                    z.object({
                        model: z.string(),
                        provider: z.string().optional(),
                        executions: z.number().int().nonnegative().optional(),
                        tokens: z.number().int().nonnegative().optional(),
                        cost_usd: z.number().nonnegative().optional(),
                        prompt_tokens: z.number().int().nonnegative().optional(),
                        completion_tokens: z.number().int().nonnegative().optional(),
                        cache_read_tokens: z.number().int().nonnegative().optional(),
                        cache_write_tokens: z.number().int().nonnegative().optional(),
                        estimated_executions: z.number().int().nonnegative().optional(),
                    })
                )
                .optional(),
            usage_quality: z
                .object({
                    has_estimated_usage: z.boolean().optional(),
                    estimated_ratio: z.number().min(0).max(1).optional(),
                })
                .optional(),
        })
        .catchall(z.unknown())
        .optional(),
    started_at: z.string().optional(),
    completed_at: z.string().optional(),
    duration_ms: z.number().optional(),
});

export const SessionHistoryResponseSchema = z.object({
    session_id: z.string(),
    tasks: z.array(SessionHistoryTaskSchema),
});

export const SessionWorkspaceResponseSchema = z.object({
    session_id: z.string(),
    version: z.number(),
    status: z.string(),
    template_id: z.string().optional(),
    selected_question_type: z.string().optional(),
    supported_question_types: z.array(z.string()).optional(),
    card_count: z.number(),
    projection_status: z.enum(["hydrated", "empty"]).optional(),
    cards: z.array(
        z.object({
            id: z.string(),
            user_id: z.string(),
            card_id: z.string(),
            suggested_question_type: z.string().optional(),
            content: z.object({
                version: z.number(),
                model: z.string(),
                data: z.object({
                    front: z.string().default(""),
                    back: z.string().default(""),
                    tags: z.array(z.string()).optional(),
                    concepts: z.array(z.string()).optional(),
                }),
                media: z.array(z.unknown()).optional(),
            }),
            edit_state: z.object({
                status: z.enum(["draft", "ai_editing", "user_editing", "confirmed"]),
                locked_by: z.string().optional(),
                locked_at: z.string().optional(),
                expires_at: z.string().optional(),
            }),
            concepts: z.array(z.string()).default([]),
            meta: z.object({
                created_at: z.string(),
                modified_at: z.string(),
                manual_edits: z.number(),
            }),
            deleted_at: z.string().optional(),
        })
    ),
});

export const SessionStateResponseSchema = z.object({
    session_id: z.string(),
    status: z.enum(["idle", "running", "completed", "failed", "paused", "cancelled"]),
    active_task_id: z.string().optional(),
    task_state: z.enum(["IDLE", "RUNNING", "PAUSED", "SUCCEEDED", "FAILED", "CANCELED"]).optional(),
    session_control_state: z.enum(["IDLE", "ACTIVE_RUNNING", "ACTIVE_PAUSED", "TERMINATING"]).optional(),
    version: z.number().int().nonnegative().optional(),
    updated_at: z.string().optional(),
});

export type SessionRecord = z.infer<typeof SessionSchema>;
export type SessionListResponseRecord = z.infer<typeof SessionListResponseSchema>;
export type SessionConversationResponseRecord = z.infer<typeof SessionConversationResponseSchema>;
export type SessionTimelineResponseRecord = z.infer<typeof SessionTimelineResponseSchema>;
export type SessionHistoryResponseRecord = z.infer<typeof SessionHistoryResponseSchema>;
export type SessionWorkspaceResponseRecord = z.infer<typeof SessionWorkspaceResponseSchema>;
export type SessionStateResponseRecord = z.infer<typeof SessionStateResponseSchema>;

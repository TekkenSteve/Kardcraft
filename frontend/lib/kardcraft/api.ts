"use client";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_PATH || "").replace(/\/$/, "");

function apiUrl(path: string): string {
    const normalizedPath = path.startsWith("/") ? path : `/${path}`;
    return `${API_BASE_URL}${normalizedPath}`;
}

async function fetchWithTimeout(input: string, init: RequestInit, timeoutMs: number): Promise<Response> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
        return await fetch(input, {
            ...init,
            signal: controller.signal,
        });
    } finally {
        clearTimeout(timeout);
    }
}

// Auth headers helper - Kratos uses cookies for authentication
// We don't need to manually add Authorization headers since cookies are sent automatically
function getAuthHeaders(): Record<string, string> {
    const headers: Record<string, string> = {};

    // For API calls, we rely on cookies being sent automatically by the browser
    // The withCredentials: true or credentials: "include" option handles this

    return headers;
}

export interface TaskSubmitRequest {
    query: string;
    task_type?: string;  // 添加 task_type 字段，默认为 "main"
    session_id?: string;
    context?: Record<string, unknown>;
    research_strategy?: "quick" | "standard" | "deep" | "academic";
    max_concurrent_agents?: number;
}

export interface TaskSubmitResponse {
    task_id?: string;
    workflow_id: string;
    status: string;
    message?: string;
    created_at: string;
    stream_url?: string;
    session_id?: string;
}

export type TaskStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

const TASK_STATUS_MAP: Record<string, TaskStatus> = {
    TASK_STATUS_QUEUED: "queued",
    TASK_STATUS_RUNNING: "running",
    TASK_STATUS_COMPLETED: "completed",
    TASK_STATUS_FAILED: "failed",
    TASK_STATUS_CANCELLED: "cancelled",
    queued: "queued",
    running: "running",
    completed: "completed",
    failed: "failed",
    cancelled: "cancelled",
};

export function parseTaskStatus(value: unknown): TaskStatus {
    if (typeof value !== "string") {
        throw new Error("Invalid task status: non-string");
    }
    const mapped = TASK_STATUS_MAP[value];
    if (!mapped) {
        throw new Error(`Invalid task status: ${value}`);
    }
    return mapped;
}

export interface TaskDetailResponse {
    task_id?: string;
    workflow_id?: string;
    query?: string;
    created_at?: string;
    session_id?: string;
    status: TaskStatus;
    raw_status: string;
    error_message?: string;
    final_output?: unknown;
    result?: unknown;
    metadata?: Record<string, unknown>;
    [key: string]: unknown;
}

export async function submitTask(request: TaskSubmitRequest): Promise<TaskSubmitResponse> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);

    const headers = {
        "Content-Type": "application/json",
        ...getAuthHeaders(),
    } as Record<string, string>;

    // Debug: log cookies and request details
    if (typeof document !== 'undefined') {
        console.log('Current cookies:', document.cookie);
        console.log('API request URL:', apiUrl("/api/v1/tasks"));
        console.log('Request headers:', headers);
    }

    // 统一请求结构：与 submitTaskWithFiles 保持一致，避免 context 丢失
    const requestWithDefaults = {
        task_type: request.task_type || "main",
        query: request.query,
        input: {
            session_id: request.session_id,
            context: request.context,
            research_strategy: request.research_strategy,
        },
        config: request.max_concurrent_agents
            ? { max_concurrent_agents: request.max_concurrent_agents }
            : undefined,
    };

    try {
        const response = await fetch(apiUrl("/api/v1/tasks"), {
            method: "POST",
            headers,
            credentials: "include", // Important: send cookies
            body: JSON.stringify(requestWithDefaults),
            signal: controller.signal,
        });

        if (!response.ok) {
            const richError = await extractApiError(response, "Failed to submit task");
            if (response.status === 401 || richError.code === "unauthenticated") {
                notifyAuthStateChanged();
            }
            console.error('API Error:', {
                status: response.status,
                statusText: response.statusText,
                error: richError.message,
                headers: Object.fromEntries(response.headers.entries())
            });
            throw richError;
        }

        return response.json();
    } finally {
        clearTimeout(timeout);
    }
}

export async function getTask(taskId: string): Promise<TaskDetailResponse> {
    const response = await fetch(apiUrl(`/api/v1/tasks/${taskId}`), {
        credentials: "include",
    });

    await assertApiOk(response, "Failed to get task");

    const payload = await response.json() as Record<string, unknown>;
    const rawStatus = typeof payload.status === "string" ? payload.status : "";
    return {
        ...payload,
        raw_status: rawStatus,
        status: parseTaskStatus(rawStatus),
    };
}

export interface TaskListResponse {
    tasks: Array<{
        task_id: string;
        query: string;
        status: string;
        mode: string;
        created_at: string;
        completed_at?: string;
        total_token_usage: {
            total_tokens: number;
            cost_usd: number;
            prompt_tokens: number;
            completion_tokens: number;
        };
    }>;
    total_count: number;
}

export async function listTasks(limit: number = 50, offset: number = 0): Promise<TaskListResponse> {
    const response = await fetch(apiUrl(`/api/v1/tasks?limit=${limit}&offset=${offset}`), {
        credentials: "include",
    });

    await assertApiOk(response, "Failed to list tasks");

    return response.json();
}

export function getStreamUrl(workflowId: string): string {
    return apiUrl(`/api/v1/stream/sse?workflow_id=${encodeURIComponent(workflowId)}`);
}

// Session Types

export interface Session {
    session_id: string;
    user_id: string;
    title?: string;
    pinned?: boolean;
    task_count: number;
    tokens_used: number;
    token_budget?: number;
    created_at: string;
    updated_at?: string;
    expires_at?: string;
    context?: Record<string, unknown>;
    // Activity tracking
    last_activity_at?: string;
    is_active?: boolean;
    // Task success metrics
    successful_tasks?: number;
    failed_tasks?: number;
    success_rate?: number;
    // Cost tracking
    total_cost_usd?: number;
    average_cost_per_task?: number;
    // Budget utilization
    budget_utilization?: number;
    budget_remaining?: number;
    is_near_budget_limit?: boolean;
    // Latest task preview
    latest_task_query?: string;
    latest_task_status?: string;
    // Research detection
    is_research_session?: boolean;
    first_task_mode?: string;
    research_strategy?: string;
}

export interface SessionListResponse {
    sessions: Session[];
    total_count: number;
}

export interface CardTemplate {
    template_id: string;
    name: string;
    description?: string;
    scope: "system" | "user" | "org";
    owner_user_id?: string;
    status: "active" | "archived" | "disabled";
    is_default: boolean;
    latest_version: number;
    tags?: unknown;
    metadata?: unknown;
    version_published?: boolean;
    created_at: string;
    updated_at: string;
}

export interface CardTemplateListResponse {
    templates: CardTemplate[];
    total_count: number;
    user_default_template_id?: string;
    user_default_template_version?: number;
}

export interface UserTemplatePreference {
    user_id: string;
    default_template_id: string;
    default_template_version?: number;
    updated_at: string;
}

export interface TemplateImportRequest {
    template_id: string;
    name: string;
    description?: string;
    version?: number;
    front_html: string;
    back_html: string;
    css: string;
    js?: string;
    tags?: unknown;
    metadata?: unknown;
    assets_manifest?: unknown;
    mapping_spec?: unknown;
    compatibility?: unknown;
    changelog?: string;
    is_published?: boolean;
}

export interface TemplatePackageV1 {
    schema_version: "kctpl/v1";
    exported_at?: string;
    template: {
        template_id: string;
        name: string;
        description?: string;
        tags?: unknown;
        metadata?: unknown;
    };
    version: {
        template_id: string;
        version: number;
        front_html: string;
        back_html: string;
        css: string;
        js?: string;
        assets_manifest?: unknown;
        mapping_spec?: unknown;
        compatibility?: unknown;
        changelog?: string;
        is_published?: boolean;
    };
}

export interface CardTemplateExportResponse {
    schema_version: "kctpl/v1";
    exported_at?: string;
    template: CardTemplate;
    version: {
        template_id: string;
        version: number;
        front_html: string;
        back_html: string;
        css: string;
        js?: string;
        assets_manifest?: unknown;
        mapping_spec?: unknown;
        compatibility?: unknown;
        changelog?: string;
        is_published: boolean;
    };
}

export interface TemplatePreviewRequest {
    template_id?: string;
    version?: number;
    front_html?: string;
    back_html?: string;
    css?: string;
    js?: string;
    sample_fields?: Record<string, string | number | boolean>;
    render_target?: string;
    template_profile?: string;
    preview_mode?: "safe" | "high_fidelity";
}

export interface TemplatePreviewResponse {
    template_id: string;
    template_version: number;
    template_profile: string;
    available_profiles: string[];
    capabilities: Record<string, boolean>;
    preview_mode: "safe" | "high_fidelity";
    front_html_rendered: string;
    back_html_rendered: string;
    front_document: string;
    back_document: string;
    css: string;
    media_tags?: string[];
    note_fields: string[];
    warnings?: string[];
    validation?: {
        ok: boolean;
        errors?: Array<{
            code: string;
            message: string;
            field?: string;
            suggestion?: string;
        }>;
        warnings?: string[];
    };
}

export interface TemplateValidationResponse {
    valid: boolean;
    validation: {
        ok: boolean;
        errors?: Array<{
            code: string;
            message: string;
            field?: string;
            suggestion?: string;
        }>;
        warnings?: string[];
    };
    note_fields: string[];
    available_profiles: string[];
    capabilities: Record<string, boolean>;
}

export interface TemplateRequiredFieldsResponse {
    field_names: string[];
    card_templates: Array<{
        template_ord: number;
        mode: string;
        required_field_ords: number[];
        required_field_names: string[];
    }>;
    required_fields_per_card: Record<string, string[]>;
}

export interface TemplatePrecheckResponse {
    would_generate_empty: boolean;
    card_count: number;
    empty_cards: number[];
    is_multi_card: boolean;
}

// Legacy history/events shapes removed in favor of the clean session contract.

// Session API Functions

export async function listSessions(limit: number = 20, offset: number = 0): Promise<SessionListResponse> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    const headers = { ...getAuthHeaders() } as Record<string, string>;

    try {
    const response = await fetch(apiUrl(`/api/v1/sessions?limit=${limit}&offset=${offset}`), {
            method: "GET",
            headers,
            credentials: "include", // Important: send cookies
            signal: controller.signal,
        });

        await assertApiOk(response, "Failed to list sessions");

        return response.json();
    } finally {
        clearTimeout(timeout);
    }
}

export async function getSession(sessionId: string): Promise<Session> {
    const response = await fetchWithTimeout(apiUrl(`/api/v1/sessions/${sessionId}`), {
        credentials: "include",
    }, 10000);

    await assertApiOk(response, "Failed to get session");

    return response.json();
}

export async function updateSession(sessionId: string, update: { title?: string; pinned?: boolean }): Promise<void> {
    const response = await fetch(apiUrl(`/api/v1/sessions/${sessionId}`), {
        method: "PATCH",
        headers: {
            "Content-Type": "application/json",
            ...getAuthHeaders(),
        },
        credentials: "include",
        body: JSON.stringify(update),
    });

    await assertApiOk(response, "Failed to update session");
}

export async function deleteSession(sessionId: string): Promise<void> {
    const response = await fetch(apiUrl(`/api/v1/sessions/${sessionId}`), {
        method: "DELETE",
        credentials: "include",
    });

    await assertApiOk(response, "Failed to delete session");
}

export async function listCardTemplates(limit: number = 50, offset: number = 0): Promise<CardTemplateListResponse> {
    const response = await fetch(apiUrl(`/api/v1/card-templates?limit=${limit}&offset=${offset}`), {
        method: "GET",
        credentials: "include",
    });

    await assertApiOk(response, "Failed to list card templates");

    return response.json();
}

export async function getUserTemplatePreference(): Promise<UserTemplatePreference> {
    const response = await fetch(apiUrl("/api/v1/users/me/template-preferences"), {
        method: "GET",
        credentials: "include",
    });

    await assertApiOk(response, "Failed to get user template preference");

    return response.json();
}

export async function setUserTemplatePreference(input: {
    default_template_id: string;
    default_template_version?: number;
}): Promise<UserTemplatePreference> {
    const response = await fetch(apiUrl("/api/v1/users/me/template-preferences"), {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...getAuthHeaders(),
        },
        credentials: "include",
        body: JSON.stringify(input),
    });

    await assertApiOk(response, "Failed to set user template preference");

    return response.json();
}

export async function importCardTemplate(input: TemplatePackageV1 | TemplateImportRequest): Promise<{ ok: boolean; template_id: string; version: number; schema_version?: string }> {
    const response = await fetch(apiUrl("/api/v1/card-templates"), {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...getAuthHeaders(),
        },
        credentials: "include",
        body: JSON.stringify(input),
    });

    await assertApiOk(response, "Failed to import card template");
    return response.json();
}

export async function exportCardTemplate(templateId: string, version?: number): Promise<CardTemplateExportResponse> {
    const suffix = version ? `?version=${encodeURIComponent(String(version))}` : "";
    const response = await fetch(apiUrl(`/api/v1/card-templates/${encodeURIComponent(templateId)}/export${suffix}`), {
        method: "GET",
        credentials: "include",
    });

    await assertApiOk(response, "Failed to export card template");
    return response.json();
}

export async function previewCardTemplate(input: TemplatePreviewRequest): Promise<TemplatePreviewResponse> {
    const response = await fetch(apiUrl("/api/v1/card-templates/preview"), {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...getAuthHeaders(),
        },
        credentials: "include",
        body: JSON.stringify(input),
    });

    await assertApiOk(response, "Failed to preview card template");
    return response.json();
}

export async function validateCardTemplate(input: {
    template_id?: string;
    version?: number;
    front_html?: string;
    back_html?: string;
    css?: string;
    js?: string;
    sample_fields?: Record<string, string | number | boolean>;
    template_profile?: string;
    mapping_spec?: Record<string, unknown>;
}): Promise<TemplateValidationResponse> {
    const response = await fetch(apiUrl("/api/v1/card-templates/validate"), {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...getAuthHeaders(),
        },
        credentials: "include",
        body: JSON.stringify(input),
    });
    await assertApiOk(response, "Failed to validate card template");
    return response.json();
}

export async function getTemplateRequiredFields(input: {
    template_id?: string;
    version?: number;
    front_html?: string;
    back_html?: string;
    css?: string;
}): Promise<TemplateRequiredFieldsResponse> {
    const response = await fetch(apiUrl("/api/v1/card-templates/required-fields"), {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...getAuthHeaders(),
        },
        credentials: "include",
        body: JSON.stringify(input),
    });
    await assertApiOk(response, "Failed to get template required fields");
    return response.json();
}

export async function precheckCardTemplate(input: {
    template_id?: string;
    version?: number;
    front_html?: string;
    back_html?: string;
    css?: string;
    sample_fields?: Record<string, string | number | boolean>;
    samples?: Array<Record<string, string | number | boolean>>;
}): Promise<TemplatePrecheckResponse> {
    const response = await fetch(apiUrl("/api/v1/card-templates/precheck"), {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...getAuthHeaders(),
        },
        credentials: "include",
        body: JSON.stringify(input),
    });
    await assertApiOk(response, "Failed to precheck card template");
    return response.json();
}

// Legacy history/events endpoints removed in favor of clean session contract endpoints.

// Session API (v1 clean contract)

export interface ConversationMessage {
    id: string;
    role: "user" | "assistant" | "system";
    content: string;
    timestamp?: string;
    task_id?: string;
    metadata?: Record<string, unknown>;
}

export interface SessionConversationResponse {
    session_id: string;
    messages: ConversationMessage[];
}

export interface TimelineEvent {
    id: number;
    type: string;
    message?: string;
    timestamp?: string;
    workflow_id?: string;
    task_id?: string;
    stream_id?: string;
    payload?: unknown;
}

export interface SessionTimelineResponse {
    session_id: string;
    events: TimelineEvent[];
}

export interface SessionHistoryResponse {
    session_id: string;
    tasks: Array<{
        task_id: string;
        workflow_id: string;
        query?: string;
        status?: string;
        mode?: string;
        model_used?: string;
        provider?: string;
        error_message?: string;
        total_tokens?: number;
        total_cost_usd?: number;
        usage_projection_status?: "pending" | "partial" | "finalized" | "invalid";
        usage_projection_reason?: string;
        metadata?: Record<string, unknown>;
        started_at?: string;
        completed_at?: string;
        duration_ms?: number;
    }>;
}

export interface SessionWorkspaceResponse {
    session_id: string;
    version: number;
    status: string;
    card_count: number;
    cards: unknown[];
}

export interface SessionStateResponse {
    session_id: string;
    status: "idle" | "running" | "completed" | "failed" | "paused" | "cancelled" | "canceled";
    active_task_id?: string;
    task_state?: "IDLE" | "RUNNING" | "PAUSED" | "SUCCEEDED" | "FAILED" | "CANCELED";
    session_control_state?: "IDLE" | "ACTIVE_RUNNING" | "ACTIVE_PAUSED" | "TERMINATING";
    version?: number;
    updated_at?: string;
}

export interface ApiErrorEnvelope {
    error: {
        code: string;
        message: string;
        details?: Record<string, unknown>;
    };
}

export class ApiError extends Error {
    code: string | null;
    status: number;
    details?: Record<string, unknown>;

    constructor(params: {
        message: string;
        code?: string | null;
        status: number;
        details?: Record<string, unknown>;
    }) {
        super(params.message);
        this.name = "ApiError";
        this.code = params.code ?? null;
        this.status = params.status;
        this.details = params.details;
    }
}

export function isUnauthenticatedApiError(err: unknown): err is ApiError {
    return err instanceof ApiError && (err.status === 401 || err.code === "unauthenticated");
}

export function toUiErrorMessage(err: unknown, fallback: string): string {
    if (isUnauthenticatedApiError(err)) {
        return "Session expired or not authenticated. Please sign in again.";
    }
    if (err instanceof ApiError || err instanceof Error) {
        return err.message || fallback;
    }
    return fallback;
}

function nextIdempotencyKey(): string {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        return crypto.randomUUID();
    }
    return `session-control-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

async function extractApiError(response: Response, fallbackPrefix: string): Promise<ApiError> {
    const text = await response.text();
    try {
        const payload = JSON.parse(text) as Partial<ApiErrorEnvelope>;
        const code = payload?.error?.code;
        const message = payload?.error?.message;
        if (code && message) {
            return new ApiError({
                message: `${fallbackPrefix}: ${code} - ${message}`,
                code,
                status: response.status,
                details: payload?.error?.details,
            });
        }
    } catch {
        // fall through to text fallback
    }
    return new ApiError({
        message: `${fallbackPrefix}: ${response.statusText}${text ? ` - ${text}` : ""}`,
        status: response.status,
    });
}

function notifyAuthStateChanged() {
    if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("auth-state-changed"));
    }
}

async function assertApiOk(response: Response, fallbackPrefix: string): Promise<void> {
    if (response.ok) return;
    const error = await extractApiError(response, fallbackPrefix);
    if (response.status === 401 || error.code === "unauthenticated") {
        notifyAuthStateChanged();
    }
    throw error;
}

export async function getSessionConversation(sessionId: string): Promise<SessionConversationResponse> {
    const response = await fetchWithTimeout(apiUrl(`/api/v1/sessions/${sessionId}/conversation`), {
        credentials: "include",
    }, 10000);

    await assertApiOk(response, "Failed to get session conversation");

    return response.json();
}

export async function getSessionTimeline(sessionId: string, limit: number = 500, offset: number = 0, includePayload: boolean = true): Promise<SessionTimelineResponse> {
    const params = new URLSearchParams({
        limit: limit.toString(),
        offset: offset.toString(),
    });

    if (includePayload) {
        params.append('include_payload', 'true');
    }

    const response = await fetchWithTimeout(apiUrl(`/api/v1/sessions/${sessionId}/timeline?${params.toString()}`), {
        credentials: "include",
    }, 10000);

    await assertApiOk(response, "Failed to get session timeline");

    return response.json();
}

export async function getSessionHistory(sessionId: string): Promise<SessionHistoryResponse> {
    const response = await fetchWithTimeout(apiUrl(`/api/v1/sessions/${sessionId}/history`), {
        credentials: "include",
    }, 10000);

    await assertApiOk(response, "Failed to get session history");

    return response.json();
}

export async function getSessionWorkspace(sessionId: string): Promise<SessionWorkspaceResponse> {
    const response = await fetch(apiUrl(`/api/v1/sessions/${sessionId}/workspace`), {
        credentials: "include",
    });

    if (response.status === 404) {
        return {
            session_id: sessionId,
            version: 0,
            status: "not_started",
            card_count: 0,
            cards: [],
        };
    }

    await assertApiOk(response, "Failed to get session workspace");

    return response.json();
}

export async function getSessionState(sessionId: string): Promise<SessionStateResponse> {
    const response = await fetch(apiUrl(`/api/v1/sessions/${sessionId}/state`), {
        credentials: "include",
    });

    await assertApiOk(response, "Failed to get session state");

    return response.json();
}

// Task Control Types

export interface TaskControlResponse {
    success: boolean;
    message: string;
    workflow_id: string;
}

export interface ControlStateResponse {
    is_paused: boolean;
    is_cancelled: boolean;
    paused_at: string;
    pause_reason: string;
    paused_by: string;
    cancel_reason: string;
    cancelled_by: string;
}

// Task Control API Functions

export async function pauseTask(taskId: string, reason?: string): Promise<TaskControlResponse> {
    const response = await fetch(apiUrl(`/api/v1/tasks/${taskId}/pause`), {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": nextIdempotencyKey(),
        },
        credentials: "include",
        body: JSON.stringify(reason ? { reason } : {}),
    });

    await assertApiOk(response, "Failed to pause task");

    return response.json();
}

export async function resumeTask(taskId: string, reason?: string): Promise<TaskControlResponse> {
    const response = await fetch(apiUrl(`/api/v1/tasks/${taskId}/resume`), {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": nextIdempotencyKey(),
        },
        credentials: "include",
        body: JSON.stringify(reason ? { reason } : {}),
    });

    await assertApiOk(response, "Failed to resume task");

    return response.json();
}

export async function cancelTask(taskId: string, reason?: string): Promise<TaskControlResponse> {
    const response = await fetch(apiUrl(`/api/v1/tasks/${taskId}/cancel`), {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": nextIdempotencyKey(),
        },
        credentials: "include",
        body: JSON.stringify(reason ? { reason } : {}),
    });

    await assertApiOk(response, "Failed to cancel task");

    return response.json();
}

export async function getTaskControlState(taskId: string): Promise<ControlStateResponse> {
    const response = await fetch(apiUrl(`/api/v1/tasks/${taskId}/control-state`), {
        credentials: "include",
    });

    await assertApiOk(response, "Failed to get task control state");

    return response.json();
}

// Schedule Types

export type ScheduleStatus = 'ACTIVE' | 'PAUSED' | 'DELETED';
export type ScheduleRunStatus = 'COMPLETED' | 'FAILED' | 'RUNNING' | 'UNKNOWN';

export interface ScheduleInfo {
    schedule_id: string;
    name: string;
    description?: string;
    cron_expression: string;
    timezone: string;
    task_query: string;
    task_context?: Record<string, unknown>;
    status: ScheduleStatus;
    next_run_at?: string;
    last_run_at?: string;
    total_runs: number;
    successful_runs: number;
    failed_runs: number;
    max_budget_per_run_usd?: number;
    timeout_seconds?: number;
    created_at: string;
}

export interface ScheduleRun {
    workflow_id: string;
    query: string;
    status: ScheduleRunStatus;
    result?: string;
    error_message?: string;
    model_used?: string;
    provider?: string;
    total_tokens: number;
    total_cost_usd: number;
    duration_ms?: number;
    triggered_at: string;
    started_at?: string;
    completed_at?: string;
}

export interface ScheduleListResponse {
    schedules: ScheduleInfo[];
    total_count: number;
}

export interface ScheduleRunsResponse {
    runs: ScheduleRun[];
    total_count: number;
    page: number;
    page_size: number;
}

export interface CreateScheduleRequest {
    name: string;
    description?: string;
    cron_expression: string;
    timezone?: string;
    task_query: string;
    task_context?: Record<string, string>;  // Backend expects map[string]string
    max_budget_per_run_usd?: number;
    timeout_seconds?: number;
}

export interface UpdateScheduleRequest {
    name?: string;
    description?: string;
    cron_expression?: string;
    timezone?: string;
    task_query?: string;
    task_context?: Record<string, string>;  // Backend expects map[string]string
    clear_task_context?: boolean;
    max_budget_per_run_usd?: number;
    timeout_seconds?: number;
}

// Schedule API Functions

export async function listSchedules(
    pageSize: number = 50,
    page: number = 1,
    status?: ScheduleStatus
): Promise<ScheduleListResponse> {
    const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
    });
    if (status) {
        params.set('status', status);
    }

    const response = await fetch(apiUrl(`/api/v1/schedules?${params}`), {
        headers: getAuthHeaders(),
        credentials: "include",
    });

    await assertApiOk(response, "Failed to list schedules");

    return response.json();
}

export async function getSchedule(scheduleId: string): Promise<ScheduleInfo> {
    const response = await fetch(apiUrl(`/api/v1/schedules/${scheduleId}`), {
        headers: getAuthHeaders(),
        credentials: "include",
    });

    await assertApiOk(response, "Failed to get schedule");

    return response.json();
}

export async function getScheduleRuns(
    scheduleId: string,
    page: number = 1,
    pageSize: number = 20
): Promise<ScheduleRunsResponse> {
    const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
    });

    const response = await fetch(apiUrl(`/api/v1/schedules/${scheduleId}/runs?${params}`), {
        headers: getAuthHeaders(),
        credentials: "include",
    });

    await assertApiOk(response, "Failed to get schedule runs");

    return response.json();
}

export async function createSchedule(request: CreateScheduleRequest): Promise<ScheduleInfo> {
    const response = await fetch(apiUrl("/api/v1/schedules"), {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...getAuthHeaders(),
        },
        credentials: "include",
        body: JSON.stringify(request),
    });

    await assertApiOk(response, "Failed to create schedule");

    return response.json();
}

export async function updateSchedule(
    scheduleId: string,
    request: UpdateScheduleRequest
): Promise<ScheduleInfo> {
    const response = await fetch(apiUrl(`/api/v1/schedules/${scheduleId}`), {
        method: "PUT",
        headers: {
            "Content-Type": "application/json",
            ...getAuthHeaders(),
        },
        credentials: "include",
        body: JSON.stringify(request),
    });

    await assertApiOk(response, "Failed to update schedule");

    return response.json();
}

export async function pauseSchedule(scheduleId: string, reason?: string): Promise<ScheduleInfo> {
    const response = await fetch(apiUrl(`/api/v1/schedules/${scheduleId}/pause`), {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...getAuthHeaders(),
        },
        credentials: "include",
        body: JSON.stringify(reason ? { reason } : {}),
    });

    await assertApiOk(response, "Failed to pause schedule");

    return response.json();
}

export async function resumeSchedule(scheduleId: string, reason?: string): Promise<ScheduleInfo> {
    const response = await fetch(apiUrl(`/api/v1/schedules/${scheduleId}/resume`), {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...getAuthHeaders(),
        },
        credentials: "include",
        body: JSON.stringify(reason ? { reason } : {}),
    });

    await assertApiOk(response, "Failed to resume schedule");

    return response.json();
}

export async function deleteSchedule(scheduleId: string): Promise<void> {
    const response = await fetch(apiUrl(`/api/v1/schedules/${scheduleId}`), {
        method: "DELETE",
        headers: getAuthHeaders(),
        credentials: "include",
    });

    await assertApiOk(response, "Failed to delete schedule");
}

// Legacy cards endpoint removed in favor of workspace.

export async function bulkUpdateCardStatus(sessionId: string, cardIds: string[], status: string): Promise<void> {
    const response = await fetch(apiUrl(`/api/v1/cards/${sessionId}/bulk`), {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...getAuthHeaders(),
        },
        credentials: "include",
        body: JSON.stringify({
            action: "update_status",
            card_ids: cardIds,
            status,
        }),
    });

    await assertApiOk(response, "Failed to update card status");
}

export async function bulkUpdateCardQuestionType(sessionId: string, cardIds: string[], questionType: string): Promise<void> {
    const response = await fetch(apiUrl(`/api/v1/cards/${sessionId}/bulk`), {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...getAuthHeaders(),
        },
        credentials: "include",
        body: JSON.stringify({
            action: "update_question_type",
            card_ids: cardIds,
            question_type: questionType,
        }),
    });

    await assertApiOk(response, "Failed to update card question type");
}

export interface ApkgExportRecord {
    export_id: string;
    session_id: string;
    template_id?: string;
    status: "processing" | "completed" | "failed";
    deck_name?: string;
    package_name?: string;
    confirmed_count?: number;
    file_name?: string;
    file_size?: number;
    download_path?: string;
    created_at: string;
    updated_at: string;
    completed_at?: string;
    error?: string;
}

export async function createApkgExport(input: {
    session_id: string;
    template_id?: string;
    deck_name?: string;
}): Promise<ApkgExportRecord> {
    const response = await fetch(apiUrl("/api/v1/exports/apkg"), {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...getAuthHeaders(),
        },
        credentials: "include",
        body: JSON.stringify(input),
    });
    await assertApiOk(response, "Failed to create apkg export");
    return response.json();
}

export async function getApkgExport(sessionId: string, exportId: string): Promise<ApkgExportRecord> {
    const response = await fetch(apiUrl(`/api/v1/exports/apkg/${encodeURIComponent(exportId)}?session_id=${encodeURIComponent(sessionId)}`), {
        method: "GET",
        credentials: "include",
    });
    await assertApiOk(response, "Failed to get apkg export");
    return response.json();
}

export function getApkgExportDownloadUrl(sessionId: string, exportId: string): string {
    return apiUrl(`/api/v1/exports/apkg/${encodeURIComponent(exportId)}/download?session_id=${encodeURIComponent(sessionId)}`);
}

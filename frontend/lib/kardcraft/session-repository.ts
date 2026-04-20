import {
    listSessions as listSessionsApi,
    getSession as getSessionApi,
    getSessionConversation as getSessionConversationApi,
    getSessionTimeline as getSessionTimelineApi,
    getSessionHistory as getSessionHistoryApi,
    getSessionWorkspace as getSessionWorkspaceApi,
    getSessionState as getSessionStateApi,
} from "./api";
import {
    SessionSchema,
    SessionListResponseSchema,
    SessionConversationResponseSchema,
    SessionTimelineResponseSchema,
    SessionHistoryResponseSchema,
    SessionWorkspaceResponseSchema,
    SessionStateResponseSchema,
    SessionRecord,
} from "./session-schemas";
import { logError } from "@/lib/observability/client";

const sessionCache = new Map<string, SessionRecord>();

const asRecord = (value: unknown): Record<string, unknown> | null => {
    if (value && typeof value === "object") {
        return value as Record<string, unknown>;
    }
    return null;
};

function normalizeListResponse(data: unknown) {
    const record = asRecord(data);
    const sessions = Array.isArray(record?.sessions) ? record.sessions : [];
    const totalCount = typeof record?.total_count === "number" ? record.total_count : sessions.length;
    if (!Array.isArray(record?.sessions) || typeof record?.total_count !== "number") {
        logError("Session list normalization", { received: data });
    }
    return { ...(record ?? {}), sessions, total_count: totalCount };
}

function normalizeConversation(data: unknown, sessionId: string) {
    const record = asRecord(data);
    const messages = Array.isArray(record?.messages) ? record.messages : [];
    if (!Array.isArray(record?.messages)) {
        logError("Conversation normalization", { sessionId, received: data });
    }
    return { ...(record ?? {}), session_id: record?.session_id || sessionId, messages };
}

function normalizeTimeline(data: unknown, sessionId: string) {
    const record = asRecord(data);
    const events = Array.isArray(record?.events) ? record.events : [];
    if (!Array.isArray(record?.events)) {
        logError("Timeline normalization", { sessionId, received: data });
    }
    return { ...(record ?? {}), session_id: record?.session_id || sessionId, events };
}

function normalizeHistory(data: unknown, sessionId: string) {
    const record = asRecord(data);
    const tasks = Array.isArray(record?.tasks) ? record.tasks : [];
    if (!Array.isArray(record?.tasks)) {
        logError("History normalization", { sessionId, received: data });
    }
    return { ...(record ?? {}), session_id: record?.session_id || sessionId, tasks };
}

function normalizeWorkspace(data: unknown, sessionId: string) {
    const record = asRecord(data);
    const cardsRaw = Array.isArray(record?.cards) ? record.cards : [];
    const cards = cardsRaw
        .map((card) => normalizeWorkspaceCard(card))
        .filter((card): card is NonNullable<ReturnType<typeof normalizeWorkspaceCard>> => card !== null);
    const projectionStatus = record?.projection_status === "hydrated" || record?.projection_status === "empty"
        ? record.projection_status
        : (cards.length > 0 ? "hydrated" : "empty");
    const supportedQuestionTypes = Array.isArray(record?.supported_question_types)
        ? record.supported_question_types.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
        : undefined;
    const templateId = typeof record?.template_id === "string" && record.template_id.trim().length > 0
        ? record.template_id
        : undefined;
    const selectedQuestionType = typeof record?.selected_question_type === "string" && record.selected_question_type.trim().length > 0
        ? record.selected_question_type
        : undefined;
    if (!Array.isArray(record?.cards)) {
        logError("Workspace normalization", { sessionId, received: data });
    }
    if (cardsRaw.length !== cards.length) {
        logError("Workspace normalization dropped invalid cards", {
            sessionId,
            total: cardsRaw.length,
            valid: cards.length,
        });
    }
    return {
        ...(record ?? {}),
        session_id: record?.session_id || sessionId,
        version: typeof record?.version === "number" ? record.version : 0,
        status: typeof record?.status === "string" ? record.status : "unknown",
        template_id: templateId,
        selected_question_type: selectedQuestionType,
        supported_question_types: supportedQuestionTypes,
        projection_status: projectionStatus,
        card_count: typeof record?.card_count === "number" ? record.card_count : cards.length,
        cards,
    };
}

function normalizeWorkspaceCard(value: unknown) {
    const card = asRecord(value);
    if (!card) return null;
    const id = typeof card.card_id === "string" && card.card_id.trim().length > 0
        ? card.card_id
        : (typeof card.id === "string" && card.id.trim().length > 0 ? card.id : "");
    if (!id) return null;

    const content = asRecord(card.content);
    const contentData = asRecord(content?.data);
    const editState = asRecord(card.edit_state);
    const meta = asRecord(card.meta);

    const status = typeof editState?.status === "string" ? editState.status : "draft";
    const normalizedStatus = status === "draft" || status === "ai_editing" || status === "user_editing" || status === "confirmed"
        ? status
        : "draft";

    const tags = Array.isArray(contentData?.tags)
        ? contentData.tags.filter((item): item is string => typeof item === "string")
        : [];
    const concepts = Array.isArray(contentData?.concepts)
        ? contentData.concepts.filter((item): item is string => typeof item === "string")
        : [];

    return {
        id,
        user_id: typeof card.user_id === "string" && card.user_id.trim().length > 0 ? card.user_id : "system",
        card_id: id,
        suggested_question_type:
            typeof card.suggested_question_type === "string" && card.suggested_question_type.trim().length > 0
                ? card.suggested_question_type
                : undefined,
        content: {
            version: typeof content?.version === "number" && Number.isFinite(content.version) ? content.version : 1,
            model: typeof content?.model === "string" && content.model.trim().length > 0 ? content.model : "mcq",
            data: {
                front: typeof contentData?.front === "string" ? contentData.front : "",
                back: typeof contentData?.back === "string" ? contentData.back : "",
                tags,
                concepts,
            },
            media: Array.isArray(content?.media) ? content.media : [],
        },
        edit_state: {
            status: normalizedStatus,
            locked_by: typeof editState?.locked_by === "string" ? editState.locked_by : undefined,
            locked_at: typeof editState?.locked_at === "string" ? editState.locked_at : undefined,
            expires_at: typeof editState?.expires_at === "string" ? editState.expires_at : undefined,
        },
        concepts,
        meta: {
            created_at: typeof meta?.created_at === "string" ? meta.created_at : new Date(0).toISOString(),
            modified_at: typeof meta?.modified_at === "string" ? meta.modified_at : new Date(0).toISOString(),
            manual_edits: typeof meta?.manual_edits === "number" && Number.isFinite(meta.manual_edits) ? meta.manual_edits : 0,
        },
        deleted_at: typeof card.deleted_at === "string" ? card.deleted_at : undefined,
    };
}

function normalizeState(data: unknown, sessionId: string) {
    const record = asRecord(data);
    return {
        ...(record ?? {}),
        session_id: record?.session_id || sessionId,
        status: record?.status || "idle",
        task_state: typeof record?.task_state === "string" ? record.task_state : "IDLE",
        session_control_state: typeof record?.session_control_state === "string" ? record.session_control_state : "IDLE",
        version: typeof record?.version === "number" ? record.version : 0,
    };
}

export async function listSessions(limit: number = 20, offset: number = 0) {
    const data = await listSessionsApi(limit, offset);
    const parsed = SessionListResponseSchema.parse(normalizeListResponse(data));
    parsed.sessions.forEach((session) => {
        sessionCache.set(session.session_id, session);
    });
    return parsed;
}

export async function getSession(sessionId: string, opts?: { force?: boolean }) {
    if (!opts?.force) {
        const cached = sessionCache.get(sessionId);
        if (cached) {
            return cached;
        }
    }
    const data = await getSessionApi(sessionId);
    const parsed = SessionSchema.parse(data);
    sessionCache.set(sessionId, parsed);
    return parsed;
}

export async function getSessionConversation(sessionId: string) {
    const data = await getSessionConversationApi(sessionId);
    return SessionConversationResponseSchema.parse(normalizeConversation(data, sessionId));
}

export async function getSessionTimeline(sessionId: string, limit: number = 500, offset: number = 0, includePayload: boolean = false) {
    const data = await getSessionTimelineApi(sessionId, limit, offset, includePayload);
    return SessionTimelineResponseSchema.parse(normalizeTimeline(data, sessionId));
}

export async function getSessionHistory(sessionId: string) {
    const data = await getSessionHistoryApi(sessionId);
    return SessionHistoryResponseSchema.parse(normalizeHistory(data, sessionId));
}

export async function getSessionWorkspace(sessionId: string) {
    const data = await getSessionWorkspaceApi(sessionId);
    return SessionWorkspaceResponseSchema.parse(normalizeWorkspace(data, sessionId));
}

export async function getSessionState(sessionId: string) {
    const data = await getSessionStateApi(sessionId);
    return SessionStateResponseSchema.parse(normalizeState(data, sessionId));
}

export function clearSessionCache(sessionId?: string) {
    if (!sessionId) {
        sessionCache.clear();
        return;
    }
    sessionCache.delete(sessionId);
}

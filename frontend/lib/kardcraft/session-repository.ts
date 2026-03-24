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
    const cards = Array.isArray(record?.cards) ? record.cards : [];
    if (!Array.isArray(record?.cards)) {
        logError("Workspace normalization", { sessionId, received: data });
    }
    return {
        ...(record ?? {}),
        session_id: record?.session_id || sessionId,
        version: typeof record?.version === "number" ? record.version : 0,
        status: typeof record?.status === "string" ? record.status : "unknown",
        card_count: typeof record?.card_count === "number" ? record.card_count : cards.length,
        cards,
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

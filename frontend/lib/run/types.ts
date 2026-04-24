import { RunEvent } from "@/lib/kardcraft/types";

export interface RunMessage {
    id: string;
    role: "user" | "assistant" | "system" | "status";
    sender?: string;
    content: string;
    timestamp?: string;
    taskId?: string;
    metadata?: Record<string, unknown>;
    isStreaming?: boolean;
    isGenerating?: boolean;
    isError?: boolean;
    isCancelled?: boolean;
    eventType?: string;
    attachments?: Array<{
        fileId: string;
        filename: string;
        size: number;
        mimeType: string;
    }>;
}

export interface CardData {
    id: string;
    user_id: string;
    card_id: string;
    suggested_question_type?: string;
    content: {
        version: number;
        model: string;
        data: {
            front: string;
            back: string;
            tags?: string[];
            concepts?: string[];
        };
        media?: {
            file_id: string;
            type: string;
            url: string;
            meta?: unknown;
        }[];
    };
    edit_state: {
        status: "draft" | "ai_editing" | "user_editing" | "confirmed";
        locked_by?: string;
        locked_at?: string;
        expires_at?: string;
    };
    concepts: string[];
    meta: {
        created_at: string;
        modified_at: string;
        manual_edits: number;
    };
    deleted_at?: string;
}

export type TemplatePreflightState = {
    status: "idle" | "running" | "passed" | "failed";
    templateId: string | null;
    templateVersion: number | null;
    questionTypes: string[];
    cardCount: number | null;
    checkedAt: string | null;
    message: string | null;
};

export type RunStatus = "idle" | "running" | "pausing" | "paused" | "cancelling" | "cancelled" | "completed" | "failed";
export type RunPhase = "idle" | "clearing" | "loading" | "hydrated" | "streaming" | "error";
export type ConnectionState = "idle" | "connecting" | "connected" | "reconnecting" | "error";
export type AgentType = "normal" | "card_template";
export type ResearchStrategy = "quick" | "standard" | "deep" | "academic";

export type RunSessionState = {
    sessionKey: string;
    sessionId: string | null;
    events: RunEvent[];
    messages: RunMessage[];
    cards: CardData[];
    cardsVersion: number;
    runPhase: RunPhase;
    status: RunStatus;
    connectionState: ConnectionState;
    streamError: string | null;
    sessionTitle: string | null;
    mainWorkflowId: string | null;
    isPaused: boolean;
    pauseCheckpoint: string | null;
    pauseReason: string | null;
    isCancelling: boolean;
    isCancelled: boolean;
    templatePreflight: TemplatePreflightState;
};

export type SessionViewModel = {
    sessionKey: string;
    sessionId: string | null;
    status: RunStatus;
    runPhase: RunPhase;
    connectionState: ConnectionState;
    streamError: string | null;
    sessionTitle: string | null;
    mainWorkflowId: string | null;
    isPaused: boolean;
    isCancelling: boolean;
    isCancelled: boolean;
    messages: RunMessage[];
    events: RunEvent[];
    cards: CardData[];
    cardsVersion: number;
};

export type RegistrySessionSummaryViewModel = {
    sessionKey: string;
    sessionId: string | null;
    status: RunStatus;
    runPhase: RunPhase;
    connectionState: ConnectionState;
    sessionTitle: string | null;
    mainWorkflowId: string | null;
};

export type RegistryViewModel = {
    activeSessionKey: string;
    selectedAgent: AgentType;
    researchStrategy: ResearchStrategy;
    sessionKeys: string[];
    sessions: RegistrySessionSummaryViewModel[];
};

export const DEFAULT_TEMPLATE_PREFLIGHT: TemplatePreflightState = {
    status: "idle",
    templateId: null,
    templateVersion: null,
    questionTypes: [],
    cardCount: null,
    checkedAt: null,
    message: null,
};

export const createInitialSessionState = (sessionKey: string, sessionId: string | null): RunSessionState => ({
    sessionKey,
    sessionId,
    events: [],
    messages: [],
    cards: [],
    cardsVersion: 0,
    runPhase: "idle",
    status: "idle",
    connectionState: "idle",
    streamError: null,
    sessionTitle: null,
    mainWorkflowId: null,
    isPaused: false,
    pauseCheckpoint: null,
    pauseReason: null,
    isCancelling: false,
    isCancelled: false,
    templatePreflight: { ...DEFAULT_TEMPLATE_PREFLIGHT },
});

export const NEW_SESSION_KEY = "session:new";
const DRAFT_SESSION_PREFIX = "draft:";

export const isDraftSessionId = (sessionId: string | null | undefined): sessionId is string => {
    if (!sessionId) return false;
    return sessionId.startsWith(DRAFT_SESSION_PREFIX);
};

export const createDraftSessionId = (): string => {
    const randomPart =
        typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
            ? crypto.randomUUID()
            : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return `${DRAFT_SESSION_PREFIX}${randomPart}`;
};

export const toSessionKey = (sessionId: string | null | undefined): string => {
    if (!sessionId || sessionId === "new") return NEW_SESSION_KEY;
    if (isDraftSessionId(sessionId)) return sessionId;
    return `session:${sessionId}`;
};

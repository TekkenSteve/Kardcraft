import type { Session } from "@/lib/kardcraft/api";

type SessionLike = Omit<Session, "title"> & {
    title?: string | null;
};

const normalizeSessionTitle = (title: string | null | undefined): string | undefined =>
    typeof title === "string" && title.trim().length > 0 ? title : undefined;

export const normalizeSessionIdentity = (session: SessionLike): Session => ({
    ...session,
    title: normalizeSessionTitle(session.title),
});

export const dedupeSessionsById = (sessions: SessionLike[]): Session[] => {
    const unique = new Map<string, Session>();
    sessions.forEach((session) => {
        unique.set(session.session_id, normalizeSessionIdentity(session));
    });
    return Array.from(unique.values());
};

import {
    SessionConversationResponseRecord,
    SessionTimelineResponseRecord,
    SessionHistoryResponseRecord,
} from "@/lib/kardcraft/session-schemas";

export type SessionDataBundle = {
    conversation: SessionConversationResponseRecord | null;
    timeline: SessionTimelineResponseRecord | null;
};

export type SessionHistoryData = SessionHistoryResponseRecord | null;

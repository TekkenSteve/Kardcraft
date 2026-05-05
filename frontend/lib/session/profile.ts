import type { Session } from "@/lib/kratos/client";

type NameParts = {
    first?: string;
    last?: string;
};

const asRecord = (value: unknown): Record<string, unknown> | null => {
    if (!value || typeof value !== "object") return null;
    return value as Record<string, unknown>;
};

function extractNameParts(value: unknown): NameParts | null {
    const record = asRecord(value);
    if (!record) return null;

    const first = typeof record.first === "string" ? record.first : undefined;
    const last = typeof record.last === "string" ? record.last : undefined;

    if (!first && !last) return null;
    return { first, last };
}

function extractEmail(session: Session | null): string | null {
    if (!session?.identity?.traits) return null;
    const traits = asRecord(session.identity.traits);
    const email = traits?.email;
    return typeof email === "string" && email.trim().length > 0 ? email : null;
}

export function getSessionDisplayName(session: Session | null): string | null {
    if (!session?.identity?.traits) return null;

    const traits = asRecord(session.identity.traits);
    if (!traits) return null;

    if (typeof traits.name === "string" && traits.name.trim().length > 0) {
        return traits.name.trim();
    }

    const nameParts = extractNameParts(traits.name);
    if (nameParts) {
        const merged = [nameParts.first, nameParts.last].filter(Boolean).join(" ").trim();
        if (merged.length > 0) return merged;
    }

    return extractEmail(session);
}

export function getSessionEmail(session: Session | null): string | null {
    return extractEmail(session);
}

export function getDisplayInitials(label: string | null | undefined): string {
    if (!label) return "?";

    const normalized = label.trim();
    if (!normalized) return "?";

    return normalized
        .split(" ")
        .filter(Boolean)
        .map((segment) => segment[0])
        .join("")
        .toUpperCase()
        .slice(0, 2);
}

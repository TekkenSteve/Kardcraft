"use client";

import { useSessionCommands, useSessionSelector } from "@/lib/session/system";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo } from "react";
import { RunDetailProvider } from "./run-detail-provider";
import { RunDetailView } from "./run-detail-view";

export default function RunDetailPage() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const { check } = useSessionCommands();
    const isAuthenticated = useSessionSelector((snapshot) => snapshot.matches("authenticated"));
    const isIdle = useSessionSelector((snapshot) => snapshot.matches("idle"));
    const isBusy = useSessionSelector(
        (snapshot) =>
            snapshot.matches("checking") ||
            snapshot.matches("authenticating") ||
            snapshot.matches("refreshing"),
    );
    const hasKnownSession = useSessionSelector(
        (snapshot) => snapshot.context.session !== null,
    );

    const returnTo = useMemo(() => {
        const query = searchParams?.toString() ?? "";
        return query ? `/run-detail?${query}` : "/run-detail";
    }, [searchParams]);
    useEffect(() => {
        check();
    }, [check]);

    useEffect(() => {
        if (!isIdle || hasKnownSession) return;
        router.replace(`/runs?auth_required=1&next=${encodeURIComponent(returnTo)}`);
    }, [hasKnownSession, isIdle, returnTo, router]);

    // Keep page mounted during transient auth checks (e.g. file picker focus/visibility changes),
    // otherwise upload UI state is destroyed on each CHECK cycle.
    if (!isAuthenticated && isBusy && !hasKnownSession) {
        return null;
    }

    if (!isAuthenticated && isIdle && !hasKnownSession) {
        return null;
    }

    return (
        <RunDetailProvider>
            <RunDetailView />
        </RunDetailProvider>
    );
}

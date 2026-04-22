"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { RunDetailProvider } from "./run-detail-provider";
import { RunDetailView } from "./run-detail-view";
import { ory } from "@/lib/kratos/client";

export default function RunDetailPage() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const [sessionReady, setSessionReady] = useState(false);

    const returnTo = useMemo(() => {
        const query = searchParams.toString();
        return query ? `/run-detail?${query}` : "/run-detail";
    }, [searchParams]);

    useEffect(() => {
        let cancelled = false;

        const verifySession = async () => {
            try {
                await ory.toSession();
                if (cancelled) return;
                setSessionReady(true);
            } catch {
                if (cancelled) return;
                router.replace(`/runs?auth_required=1&next=${encodeURIComponent(returnTo)}`);
            }
        };

        void verifySession();
        return () => {
            cancelled = true;
        };
    }, [returnTo, router]);

    if (!sessionReady) {
        return null;
    }

    return (
        <RunDetailProvider>
            <RunDetailView />
        </RunDetailProvider>
    );
}

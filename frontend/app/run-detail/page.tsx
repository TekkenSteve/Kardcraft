"use client";

import { RunDetailProvider } from "./run-detail-provider";
import { RunDetailView } from "./run-detail-view";

export default function RunDetailPage() {
    return (
        <RunDetailProvider>
            <RunDetailView />
        </RunDetailProvider>
    );
}

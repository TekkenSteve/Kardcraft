"use client";

import { useEffect } from "react";
import { TimelineDisplayEvent } from "./use-timeline";
import { RunMessage } from "@/lib/features/runSlice";

export function useScrollSync({
    timelineScrollRef,
    conversationScrollRef,
    timelineEvents,
    runStatus,
    messages,
    activeTab,
    userHasScrolledRef,
}: {
    timelineScrollRef: React.RefObject<HTMLDivElement>;
    conversationScrollRef: React.RefObject<HTMLDivElement>;
    timelineEvents: TimelineDisplayEvent[];
    runStatus: "idle" | "running" | "completed" | "failed";
    messages: RunMessage[];
    activeTab: string;
    userHasScrolledRef: React.MutableRefObject<boolean>;
}) {
    useEffect(() => {
        if (timelineScrollRef.current) {
            const scrollContainer = timelineScrollRef.current.querySelector('[data-slot="scroll-area-viewport"]');
            if (scrollContainer) {
                requestAnimationFrame(() => {
                    scrollContainer.scrollTop = scrollContainer.scrollHeight;
                });
            }
        }
    }, [timelineEvents, timelineScrollRef]);

    useEffect(() => {
        if (!conversationScrollRef.current) return;

        const scrollContainer = conversationScrollRef.current.querySelector('[data-slot="scroll-area-viewport"]');
        if (!scrollContainer) return;

        const handleScroll = () => {
            const isNearBottom = scrollContainer.scrollHeight - scrollContainer.scrollTop - scrollContainer.clientHeight < 100;
            if (!isNearBottom && runStatus === "running") {
                userHasScrolledRef.current = true;
            }
            if (isNearBottom) {
                userHasScrolledRef.current = false;
            }
        };

        scrollContainer.addEventListener('scroll', handleScroll, { passive: true });
        return () => scrollContainer.removeEventListener('scroll', handleScroll);
    }, [runStatus, conversationScrollRef, userHasScrolledRef]);

    useEffect(() => {
        if (runStatus === "running") {
            const hasOnlyUserMessage = messages.length === 1 && messages[0]?.role === "user";
            if (hasOnlyUserMessage) {
                userHasScrolledRef.current = false;
            }
        }
    }, [runStatus, messages.length, userHasScrolledRef]);

    useEffect(() => {
        if (runStatus !== "running" && runStatus !== "idle") return;
        if (userHasScrolledRef.current) return;

        if (conversationScrollRef.current && activeTab === "conversation") {
            const scrollContainer = conversationScrollRef.current.querySelector('[data-slot="scroll-area-viewport"]');
            if (scrollContainer) {
                requestAnimationFrame(() => {
                    scrollContainer.scrollTop = scrollContainer.scrollHeight;
                });
            }
        }
    }, [messages, activeTab, runStatus, conversationScrollRef, userHasScrolledRef]);
}

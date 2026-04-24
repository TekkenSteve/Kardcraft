import React, { useMemo } from "react";
import {
    CheckCircle2,
    Circle,
    AlertCircle,
    BrainCircuit,
    Terminal,
    Cpu,
    Wrench,
    Clock,
    Activity,
    ExternalLink
} from "lucide-react";
import { cn } from "@/lib/utils";
import { CollapsibleDetails } from "./collapsible-details";
import { useTranslation } from "react-i18next";

// --- Types ---
export interface TimelineEvent {
    id: string;
    type: "agent" | "llm" | "tool" | "system";
    status: "completed" | "running" | "failed" | "cancelled" | "pending" | "paused";
    title: string;
    timestamp: string;
    details?: string;
    detailsType?: "json" | "text";
    messageId?: string;
}

interface RunTimelineProps {
    events: readonly TimelineEvent[];
    onNavigateToMessage?: (messageId: string) => void;
}

export function RunTimeline({ events, onNavigateToMessage }: RunTimelineProps) {
    const { t } = useTranslation();
    const visibleEvents = useMemo(() => events.slice(-120), [events]);
    return (
        <div className="w-full max-w-xl mx-auto px-4 pb-8 pt-0 overflow-hidden">
            <div className="relative min-w-0 w-full overflow-hidden">
                {/* Thin, Precise Vertical Line */}
                <div className="absolute left-[19px] top-2 bottom-2 w-px bg-muted/30" />

                <div className="space-y-1 min-w-0 w-full">
                    {visibleEvents.map((event, index) => (
                        <TimelineItem
                            key={`${event.id}-${index}`}
                            event={event}
                            index={index}
                            onNavigate={onNavigateToMessage}
                            goToChatLabel={t("runDetail.goToChat")}
                        />
                    ))}
                </div>
            </div>

            <div className="h-12" />
        </div>
    );
}

const TimelineItem = ({
    event,
    index,
    onNavigate,
    goToChatLabel,
}: {
    event: TimelineEvent,
    index: number,
    onNavigate?: (id: string) => void,
    goToChatLabel: string,
}) => {
    const isRunning = event.status === "running";
    const isCompleted = event.status === "completed";
    const isPaused = event.status === "paused";
    const isCancelled = event.status === "cancelled";

    const getIcon = () => {
        if (isCompleted) return <CheckCircle2 className="h-3 w-3" />;
        if (event.status === "failed") return <AlertCircle className="h-3 w-3" />;
        if (event.status === "cancelled") return <Clock className="h-3 w-3" />;
        if (event.status === "paused") return <Activity className="h-3 w-3" />;

        switch (event.type) {
            case "agent": return <BrainCircuit className="h-3 w-3" />;
            case "tool": return <Wrench className="h-3 w-3" />;
            case "llm": return <Cpu className="h-3 w-3" />;
            default: return <Terminal className="h-3 w-3" />;
        }
    };

    return (
        <div
            className={cn(
                "relative pl-12 pr-8 py-3 rounded-xl transition-all min-w-0 flex flex-col group",
                isRunning ? "bg-primary/[0.03] ring-1 ring-primary/10" : "hover:bg-muted/30",
                !isRunning && !isCompleted && !isPaused && !isCancelled && "opacity-40"
            )}
        >
            {/* Minimalist Status Node */}
            <div className={cn(
                "absolute left-[13px] top-[18px] flex h-3.5 w-3.5 items-center justify-center rounded-full z-10 bg-background border transition-all duration-300",
                isRunning ? "border-primary ring-2 ring-primary/5 shadow-sm shadow-primary/10" :
                    isCompleted ? "border-emerald-500/40 text-emerald-500/70" :
                        isCancelled ? "border-yellow-600/40 text-yellow-700/80" :
                            isPaused ? "border-amber-600/40 text-amber-700/80" :
                        "border-muted/50"
            )}>
                {isRunning ? (
                    <div className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
                ) : (
                    <div className="scale-75">{getIcon()}</div>
                )}
            </div>

            <div className="flex flex-col gap-0.5 min-w-0 overflow-hidden">
                <div className="flex items-center justify-between gap-3 min-w-0">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                        <span className={cn(
                            "text-xs font-medium truncate transition-colors",
                            isRunning ? "text-primary font-bold" : "text-foreground/80"
                        )}>
                            {event.title}
                        </span>

                        {event.messageId && onNavigate && (
                            <button
                                onClick={() => onNavigate(event.messageId!)}
                                className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 text-[9px] text-primary hover:underline font-bold whitespace-nowrap shrink-0"
                            >
                                {goToChatLabel} <ExternalLink className="h-2 w-2" />
                            </button>
                        )}
                    </div>

                    <div className="text-[9px] font-mono text-muted-foreground/50 whitespace-nowrap shrink-0">
                        {event.timestamp}
                    </div>
                </div>

                {event.details && (
                    <div className="mt-1 w-full overflow-hidden">
                        <CollapsibleDetails
                            content={event.details}
                            type={event.detailsType || "text"}
                            status={event.status}
                        />
                    </div>
                )}
            </div>
        </div>
    );
};

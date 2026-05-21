"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type StatePanelAction = {
    label: string;
    onClick?: () => void;
    href?: string;
    variant?: "default" | "outline" | "secondary" | "ghost";
};

const EMPTY_ACTIONS: StatePanelAction[] = [];

export function StatePanel({
    title,
    description,
    actions = EMPTY_ACTIONS,
    tone = "neutral",
    className,
}: {
    title: string;
    description?: string;
    actions?: StatePanelAction[];
    tone?: "neutral" | "error";
    className?: string;
}) {
    return (
        <div
            className={cn(
                "rounded-lg border p-6 text-center space-y-3",
                tone === "error" ? "border-red-200 bg-red-50 text-red-900" : "bg-muted/20",
                className
            )}
        >
            <div className="text-lg font-semibold">{title}</div>
            {description && (
                <div className={cn("text-sm", tone === "error" ? "text-red-700" : "text-muted-foreground")}>
                    {description}
                </div>
            )}
            {actions.length > 0 && (
                <div className="flex flex-wrap items-center justify-center gap-2">
                    {actions.map((action) => {
                        const variant = action.variant || "outline";
                        if (action.href) {
                            return (
                                <Button key={action.label} variant={variant} asChild>
                                    <Link href={action.href}>{action.label}</Link>
                                </Button>
                            );
                        }
                        return (
                            <Button
                                key={action.label}
                                variant={variant}
                                onClick={action.onClick}
                            >
                                {action.label}
                            </Button>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

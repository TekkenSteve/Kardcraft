"use client";

import React from "react";
import { Button } from "@/components/ui/button";
import { logError } from "@/lib/observability/client";

export class ErrorBoundary extends React.Component<{
    fallbackTitle?: string;
    fallbackMessage?: string;
    retryLabel?: string;
    reloadLabel?: string;
    reportLabel?: string;
    onReset?: () => void;
    children: React.ReactNode;
}, { hasError: boolean; message: string } > {
    state = { hasError: false, message: "" };

    static getDerivedStateFromError(error: Error) {
        return { hasError: true, message: error.message || "Unexpected error" };
    }

    componentDidCatch(error: Error) {
        console.error("[ErrorBoundary]", error);
        logError(error, {
            source: "ErrorBoundary",
            route: typeof window !== "undefined" ? window.location.pathname : "unknown",
        });
    }

    handleReset = () => {
        this.setState({ hasError: false, message: "" });
        this.props.onReset?.();
    };

    handleReport = () => {
        const details = [
            `Route: ${typeof window !== "undefined" ? window.location.pathname : "unknown"}`,
            `Message: ${this.state.message || this.props.fallbackMessage || "unknown"}`,
        ].join("\n");
        if (navigator?.clipboard?.writeText) {
            navigator.clipboard.writeText(details);
        }
    };

    render() {
        if (this.state.hasError) {
            return (
                <div className="flex h-full w-full items-center justify-center p-8">
                    <div className="max-w-md text-center space-y-3">
                        <div className="text-3xl font-semibold">
                            {this.props.fallbackTitle || "Something went wrong"}
                        </div>
                        <div className="text-sm text-muted-foreground">
                            {this.props.fallbackMessage || this.state.message}
                        </div>
                        <div className="flex items-center justify-center gap-2">
                            <Button variant="outline" onClick={this.handleReset}>
                                {this.props.retryLabel || "Try again"}
                            </Button>
                            <Button onClick={() => window.location.reload()}>
                                {this.props.reloadLabel || "Reload"}
                            </Button>
                            <Button variant="outline" onClick={this.handleReport}>
                                {this.props.reportLabel || "Report"}
                            </Button>
                        </div>
                    </div>
                </div>
            );
        }

        return this.props.children;
    }
}

"use client";

import { ErrorBoundary } from "@/components/error-boundary";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { Eye, Loader2, PanelRight, PanelRightClose } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import React from "react";
import { useTranslation } from "react-i18next";
import { ConversationPanel } from "./conversation-panel";
import { useRunDetailActions, useRunDetailData, useRunDetailUi } from "./run-detail-hooks";
import { SummaryPanel } from "./summary-panel";

export function RunDetailView() {
    const { t } = useTranslation();
    const RunTimeline = React.useMemo(
        () =>
            dynamic(() => import("@/components/run-timeline").then(m => m.RunTimeline), {
                loading: () => (
                    <div className="p-4 text-sm text-muted-foreground">
                        {t("runDetail.loadingTimeline")}
                    </div>
                ),
            }),
        [t]
    );
    const CardWorkspace = React.useMemo(
        () =>
            dynamic(() => import("@/components/workspace/CardWorkspace").then(m => m.CardWorkspace), {
                loading: () => (
                    <div className="p-4 text-sm text-muted-foreground">
                        {t("runDetail.loadingWorkspace")}
                    </div>
                ),
            }),
        [t]
    );
    const {
        sessionId,
        error,
        isLoading,
        connectionState,
        streamError,
        runStatus,
        timelineEvents,
        resolvedSessionId,
        workspacePhase,
    } = useRunDetailData();
    const {
        activeTab,
        setActiveTab,
        isTimelineOpen,
        setIsTimelineOpen,
        showWorkspace,
        setShowWorkspace,
        workspaceExpanded,
        setWorkspaceExpanded,
        timelineScrollRef,
    } = useRunDetailUi();
    const {
        handleRetryStream,
        scrollToMessage,
    } = useRunDetailActions();

    if (error) {
        return (
            <div className="flex items-center justify-center h-screen">
                <div className="text-center space-y-4">
                    <div className="text-red-500 text-5xl mb-4">⚠️</div>
                    <h2 className="text-2xl font-bold">{t("runDetail.failedTitle")}</h2>
                    <p className="text-muted-foreground">{error}</p>
                    <p className="text-sm text-muted-foreground">{t("runDetail.failedHint")}</p>
                    <div className="flex items-center justify-center gap-2">
                        <Button variant="outline" onClick={() => window.location.reload()}>
                            {t("common.reload")}
                        </Button>
                        <Button
                            variant="outline"
                            onClick={() => navigator?.clipboard?.writeText(`Route: ${window.location.pathname}\nError: ${error}`)}
                        >
                            {t("common.report")}
                        </Button>
                        <Button asChild>
                            <Link href="/runs">{t("common.goBack")}</Link>
                        </Button>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <ErrorBoundary
            fallbackTitle={t("runDetail.errorBoundaryTitle")}
            fallbackMessage={t("runDetail.errorBoundaryMessage")}
            retryLabel={t("common.retry")}
            reloadLabel={t("common.reload")}
            reportLabel={t("common.report")}
        >
        <div className="flex h-full flex-col overflow-hidden">
            {isLoading && sessionId !== "new" && (
                <div className="flex items-center gap-2 border-b px-6 py-2 text-xs text-muted-foreground bg-muted/40">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>{t("runDetail.loadingSession")}</span>
                </div>
            )}

            {(connectionState === "error" || streamError) && (
                <div className="flex items-center justify-between gap-3 border-b border-red-200 bg-red-50 px-6 py-3 shrink-0">
                    <div className="text-sm text-red-700">
                        {streamError || t("runDetail.streamError")}
                        <div className="text-xs text-red-600/90 mt-1">{t("runDetail.streamErrorHint")}</div>
                    </div>
                    <div className="flex gap-2">
                        <Button variant="outline" size="sm" onClick={handleRetryStream}>
                            {t("runDetail.retryStream")}
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => window.location.reload()}>
                            {t("common.reload")}
                        </Button>
                    </div>
                </div>
            )}

            <div className="flex flex-1 overflow-hidden">
                <div className="flex-1 bg-background flex flex-col">
                    <Tabs
                        defaultValue="conversation"
                        value={activeTab}
                        onValueChange={(value) => setActiveTab(value)}
                        className="h-full flex flex-col"
                    >
                        <div className="px-4 pt-4 shrink-0 flex items-center justify-between gap-4">
                            <TabsList>
                                <TabsTrigger value="conversation">
                                    {t("runDetail.conversationTab")}
                                </TabsTrigger>
                                <TabsTrigger value="summary">
                                    {t("runDetail.summaryTab")}
                                </TabsTrigger>
                            </TabsList>
                            <div className="flex items-center gap-2">
                                {(timelineEvents.length > 0 || runStatus === "running" || runStatus === "pausing" || runStatus === "paused" || runStatus === "resuming" || runStatus === "cancelling") && (
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => setIsTimelineOpen(true)}
                                    className="gap-2"
                                    aria-label={t("runDetail.timeline")}
                                >
                                    <Eye className="h-4 w-4" />
                                    <span className="hidden sm:inline">{t("runDetail.timeline")}</span>
                                </Button>
                                )}
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => setShowWorkspace(!showWorkspace)}
                                    className={cn("gap-2 transition-all", showWorkspace && "bg-blue-50 border-blue-200 text-blue-700")}
                                    aria-label={showWorkspace ? t("runDetail.closeWorkspace") : t("runDetail.openWorkspace")}
                                >
                                    {showWorkspace ? <PanelRightClose className="h-4 w-4" /> : <PanelRight className="h-4 w-4" />}
                                    <span className="hidden sm:inline">{showWorkspace ? t("runDetail.closeWorkspace") : t("runDetail.openWorkspace")}</span>
                                </Button>
                            </div>
                        </div>

                        <TabsContent value="conversation" className="flex-1 p-0 m-0 data-[state=active]:flex flex-col overflow-hidden">
                            <ConversationPanel />
                        </TabsContent>

                        <TabsContent value="summary" className="flex-1 p-4 sm:p-6 m-0 overflow-auto min-h-0">
                            <SummaryPanel />
                        </TabsContent>
                    </Tabs>
                </div>

                {showWorkspace && !workspaceExpanded && (
                    <div className="shrink-0 h-full hidden xl:flex transition-[width] duration-300 ease-out w-[320px] lg:w-[380px]">
                        <CardWorkspace
                            sessionId={resolvedSessionId}
                            workspacePhase={workspacePhase}
                            isFullscreen={false}
                            onToggleFullscreen={() => setWorkspaceExpanded(true)}
                            onClose={() => setShowWorkspace(false)}
                        />
                    </div>
                )}
            </div>

            {showWorkspace && workspaceExpanded && (
                <div className="fixed inset-0 z-40 bg-background/96 backdrop-blur-md">
                    <CardWorkspace
                        sessionId={resolvedSessionId}
                        workspacePhase={workspacePhase}
                        isFullscreen
                        onToggleFullscreen={() => setWorkspaceExpanded(false)}
                        onClose={() => {
                            setWorkspaceExpanded(false);
                            setShowWorkspace(false);
                        }}
                    />
                </div>
            )}

            <Dialog open={isTimelineOpen} onOpenChange={setIsTimelineOpen}>
                <DialogContent className="max-w-3xl p-0">
                    <DialogHeader className="px-6 pt-6">
                        <DialogTitle>{t("runDetail.timelineTitle")}</DialogTitle>
                        <DialogDescription>
                            {t("runDetail.timelineStarting")}
                        </DialogDescription>
                    </DialogHeader>
                    <div className="px-6 pb-6">
                        <div className="h-[60vh]">
                            <ScrollArea className="h-full" ref={timelineScrollRef}>
                                {timelineEvents.length > 0 ? (
                                    <RunTimeline
                                        events={timelineEvents}
                                        onNavigateToMessage={scrollToMessage}
                                    />
                                ) : (
                                    <div className="p-4 text-sm text-muted-foreground text-center">
                                        {t("runDetail.timelineStarting")}
                                    </div>
                                )}
                            </ScrollArea>
                        </div>
                    </div>
                </DialogContent>
            </Dialog>
        </div>
        </ErrorBoundary>
    );
}

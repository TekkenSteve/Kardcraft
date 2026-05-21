"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { StatePanel } from "@/components/state-panel";
import { Search, Loader2, RefreshCw, MessageSquare, Layers, DollarSign, Sparkles, Microscope, CheckCircle2, XCircle, MoreHorizontal, Pencil, Pin, Trash2 } from "lucide-react";
import { useEffect, useState, useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Session, updateSession, deleteSession, isUnauthenticatedApiError, toUiErrorMessage } from "@/lib/kardcraft/api";
import { listSessions } from "@/lib/kardcraft/session-repository";
import { dedupeSessionsById } from "@/lib/kardcraft/session-list";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export default function RunsPage() {
    const { t } = useTranslation();
    const searchParams = useSearchParams();
    const currentSessionId = searchParams?.get("session_id") ?? null;
    const authRequired = (searchParams?.get("auth_required") ?? "") === "1";
    const [searchQuery, setSearchQuery] = useState("");
    const [editingSession, setEditingSession] = useState<Session | null>(null);
    const [editingTitle, setEditingTitle] = useState("");
    const [selectedIds, setSelectedIds] = useState<string[]>([]);
    const queryClient = useQueryClient();

    const PAGE_SIZE = 50;
    const sessionsQuery = useInfiniteQuery({
        queryKey: ["sessions", PAGE_SIZE],
        queryFn: async ({ pageParam }) => listSessions(PAGE_SIZE, pageParam as number),
        initialPageParam: 0,
        getNextPageParam: (lastPage, allPages) => {
            const loaded = allPages.reduce((sum, page) => sum + (page.sessions?.length || 0), 0);
            return loaded < (lastPage.total_count || 0) ? loaded : undefined;
        },
    });

    const mergedSessions = useMemo(() => {
        if (!sessionsQuery.data) return [];
        const merged = sessionsQuery.data.pages.flatMap(page => page.sessions || []);
        return dedupeSessionsById(merged);
    }, [sessionsQuery.data]);

    const sessions = useMemo(() => {
        if (sessionsQuery.error && isUnauthenticatedApiError(sessionsQuery.error)) {
            return [];
        }
        return mergedSessions;
    }, [mergedSessions, sessionsQuery.error]);
    const totalCount = useMemo(() => {
        if (!sessionsQuery.data) return null;
        const counts = sessionsQuery.data.pages.map((page) => page.total_count || 0);
        return counts.length > 0 ? Math.max(...counts) : null;
    }, [sessionsQuery.data]);
    const isLoading = sessionsQuery.isLoading;
    const isLoadingMore = sessionsQuery.isFetchingNextPage;
    const error = sessionsQuery.error ? toUiErrorMessage(sessionsQuery.error, "Failed to load sessions") : null;

    // Prefetch next page for faster perceived navigation
    useEffect(() => {
        if (!totalCount) return;
        if (!sessionsQuery.hasNextPage) return;
        if (totalCount <= PAGE_SIZE) return;
        const timer = setTimeout(() => {
            void sessionsQuery.fetchNextPage();
        }, 600);
        return () => clearTimeout(timer);
    }, [PAGE_SIZE, sessionsQuery, totalCount]);

    // Filter sessions based on search
    const filteredSessions = sessions.filter(session => {
        const query = searchQuery.toLowerCase();
        const title = (session.title || "").toLowerCase();
        return title.includes(query) || session.session_id.toLowerCase().includes(query);
    });

    const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
    const allSelected = filteredSessions.length > 0 && filteredSessions.every((session) => selectedSet.has(session.session_id));

    const toggleSelectAll = () => {
        if (allSelected) {
            setSelectedIds([]);
        } else {
            setSelectedIds(filteredSessions.map((session) => session.session_id));
        }
    };

    const toggleSelectOne = (sessionId: string) => {
        setSelectedIds((prev) => {
            if (prev.includes(sessionId)) {
                return prev.filter((id) => id !== sessionId);
            }
            return [...prev, sessionId];
        });
    };

    const handleEditTitle = useCallback((session: Session) => {
        setEditingSession(session);
        setEditingTitle(session.title || "");
    }, []);

    const handleSaveTitle = useCallback(async () => {
        if (!editingSession) return;
        const nextTitle = editingTitle.trim();
        await updateSession(editingSession.session_id, { title: nextTitle });
        await queryClient.invalidateQueries({ queryKey: ["sessions"] });
        setEditingSession(null);
    }, [editingSession, editingTitle, queryClient]);

    const handleTogglePin = useCallback(async (session: Session) => {
        const nextPinned = !session.pinned;
        await updateSession(session.session_id, { pinned: nextPinned });
        await queryClient.invalidateQueries({ queryKey: ["sessions"] });
    }, [queryClient]);

    const handleDeleteSession = useCallback(async (session: Session) => {
        const confirmed = window.confirm(t("sidebar.deleteConfirm"));
        if (!confirmed) return;
        await deleteSession(session.session_id);
        await queryClient.invalidateQueries({ queryKey: ["sessions"] });
    }, [queryClient, t]);

    const handleBulkPin = useCallback(async (pinned: boolean) => {
        if (selectedIds.length === 0) return;
        await Promise.all(selectedIds.map((id) => updateSession(id, { pinned })));
        await queryClient.invalidateQueries({ queryKey: ["sessions"] });
    }, [queryClient, selectedIds]);

    const handleBulkDelete = useCallback(async () => {
        if (selectedIds.length === 0) return;
        const confirmed = window.confirm(t("sidebar.deleteConfirm"));
        if (!confirmed) return;
        await Promise.all(selectedIds.map((id) => deleteSession(id)));
        setSelectedIds([]);
        await queryClient.invalidateQueries({ queryKey: ["sessions"] });
    }, [queryClient, selectedIds, t]);

    const refreshSessions = useCallback(async () => {
        await sessionsQuery.refetch();
    }, [sessionsQuery]);

    return (
        <div className="h-full overflow-y-auto p-4 sm:p-8 space-y-6 sm:space-y-8">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                    <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight">{t("runs.title")}</h1>
                    <p className="text-muted-foreground text-sm sm:text-base">
                        {t("runs.subtitle")}
                    </p>
                </div>
                <div className="flex gap-2">
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                            void refreshSessions();
                        }}
                        disabled={isLoading || isLoadingMore}
                        aria-label={t("common.refresh")}
                    >
                        <RefreshCw className={`size-4 ${isLoading ? "animate-spin" : ""}`} />
                        <span className="hidden sm:inline ml-2">{t("common.refresh")}</span>
                    </Button>
                </div>
            </div>

            <div className="flex items-center gap-4">
                <div className="relative flex-1 max-w-sm">
                    <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
                    <Input
                        type="search"
                        placeholder={t("runs.searchPlaceholder")}
                        aria-label={t("runs.searchPlaceholder")}
                        name="runs-search"
                        autoComplete="off"
                        className="pl-8"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                    />
                </div>
                {selectedIds.length > 0 && (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <span>{t("runs.selectedCount", { count: selectedIds.length })}</span>
                        <Button size="sm" variant="outline" onClick={() => handleBulkPin(true)}>
                            {t("common.pin")}
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => handleBulkPin(false)}>
                            {t("common.unpin")}
                        </Button>
                        <Button size="sm" variant="destructive" onClick={handleBulkDelete}>
                            {t("common.delete")}
                        </Button>
                    </div>
                )}
            </div>

            {error && (
                <StatePanel
                    tone="error"
                    title={t("runs.errorTitle")}
                    description={error}
                    actions={[
                        { label: t("common.retry"), onClick: () => { void refreshSessions(); }, variant: "outline" },
                        { label: t("common.reload"), onClick: () => window.location.reload(), variant: "outline" },
                    ]}
                />
            )}
            {!error && authRequired && (
                <StatePanel
                    tone="neutral"
                    title="Authentication required"
                    description="Your session has expired. Please sign in again before opening a historical session."
                    actions={[
                        { label: t("common.refresh"), onClick: () => window.location.reload(), variant: "outline" },
                    ]}
                />
            )}

            {isLoading ? (
                <div className="rounded-md border p-4 space-y-3">
                    {Array.from({ length: 6 }).map((_, idx) => (
                        <div key={`skeleton-row-${idx}`} className="h-10 rounded-md bg-muted animate-pulse" />
                    ))}
                </div>
            ) : (
                <div className="rounded-md border">
                    <div className="w-full overflow-auto">
                        <table className="w-full caption-bottom text-sm">
                            <thead className="[&_tr]:border-b">
                                <tr className="border-b transition-colors hover:bg-muted/50 data-[state=selected]:bg-muted">
                                    <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground w-10">
                                        <input
                                            type="checkbox"
                                            checked={allSelected}
                                            onChange={toggleSelectAll}
                                            aria-label={t("runs.selectAll")}
                                            className="size-4 accent-primary"
                                        />
                                    </th>
                                    <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground [&:has([role=checkbox])]:pr-0">
                                        {t("runs.sessionHeader")}
                                    </th>
                                    <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground [&:has([role=checkbox])]:pr-0 hidden md:table-cell">
                                        {t("runs.agentHeader")}
                                    </th>
                                    <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground [&:has([role=checkbox])]:pr-0 hidden sm:table-cell">
                                        {t("runs.tasksHeader")}
                                    </th>
                                    <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground [&:has([role=checkbox])]:pr-0 hidden sm:table-cell">
                                        {t("runs.costHeader")}
                                    </th>
                                    <th className="h-12 px-4 text-right align-middle font-medium text-muted-foreground [&:has([role=checkbox])]:pr-0">
                                        {t("runs.actionsHeader")}
                                    </th>
                                </tr>
                            </thead>
                            <tbody className="[&_tr:last-child]:border-0">
                                {filteredSessions.length === 0 ? (
                                    <tr>
                                        <td colSpan={6} className="p-8 text-center text-muted-foreground">
                                            <StatePanel
                                                className="mx-auto max-w-lg"
                                                title={searchQuery ? t("runs.emptySearchTitle") : t("runs.emptyTitle")}
                                                description={searchQuery ? t("runs.noSessionsSearch") : t("runs.noSessions")}
                                                actions={searchQuery ? [] : [
                                                    { label: t("runs.startTask"), href: "/run-detail?session_id=new", variant: "outline" },
                                                ]}
                                            />
                                        </td>
                                    </tr>
                                ) : (
                                    filteredSessions.map((session) => (
                                        <tr
                                            key={session.session_id}
                                            className="border-b transition-colors hover:bg-muted/50 data-[state=selected]:bg-muted"
                                        >
                                            <td className="p-4 align-middle w-10">
                                                <input
                                                    type="checkbox"
                                                    checked={selectedSet.has(session.session_id)}
                                                    onChange={() => toggleSelectOne(session.session_id)}
                                                    aria-label={t("runs.selectOne", { id: session.session_id })}
                                                    className="size-4 accent-primary"
                                                />
                                            </td>
                                            <td className="p-4 align-middle [&:has([role=checkbox])]:pr-0">
                                                <div className="flex items-start gap-2">
                                                    {(() => {
                                                        const isRunning = session.latest_task_status === "RUNNING" || session.latest_task_status === "QUEUED";
                                                        const isActive = session.is_active || isRunning;
                                                        // Friendly title: prefer title, else truncated query, else "New task…"
                                                        const truncatedQuery = session.latest_task_query 
                                                            ? (session.latest_task_query.length > 50 
                                                                ? session.latest_task_query.slice(0, 50) + "…" 
                                                                : session.latest_task_query)
                                                            : null;
                                                        const displayTitle = session.title || truncatedQuery || t("runs.newTaskPlaceholder");
                                                        const hasRealTitle = !!session.title;
                                                        // Only show query below if we have a real title (avoid redundancy)
                                                        const showQueryBelow = hasRealTitle && session.latest_task_query;
                                                        return (
                                                            <>
                                                            <TooltipProvider>
                                                                <Tooltip>
                                                                    <TooltipTrigger asChild>
                                                                        <div className={`mt-1.5 size-2 rounded-full shrink-0 ${
                                                                            isRunning ? "bg-blue-500 animate-pulse" : 
                                                                            isActive ? "bg-emerald-500" : "bg-gray-300"
                                                                        }`} />
                                                                    </TooltipTrigger>
                                                                    <TooltipContent suppressHydrationWarning>
                                                                        <p suppressHydrationWarning>{isRunning 
                                                                            ? t("runs.running") 
                                                                            : isActive 
                                                                                ? t("runs.active", { when: session.last_activity_at ? new Date(session.last_activity_at).toLocaleString() : t("runs.recently") })
                                                                                : t("runs.inactive")}</p>
                                                                    </TooltipContent>
                                                                </Tooltip>
                                                            </TooltipProvider>
                                                            <div className="flex flex-col min-w-0">
                                                                <Link
                                                                    href={`/run-detail?session_id=${session.session_id}`}
                                                                    className={`font-medium truncate max-w-[280px] hover:text-primary hover:underline transition-colors ${!hasRealTitle ? 'text-muted-foreground' : ''}`}
                                                                    title={session.title || session.latest_task_query || session.session_id}
                                                                    onClick={(event) => {
                                                                        if (currentSessionId === session.session_id) {
                                                                            event.preventDefault();
                                                                        }
                                                                    }}
                                                                >
                                                                    {displayTitle}
                                                                </Link>
                                                                 <span className="text-xs text-muted-foreground" suppressHydrationWarning>
                                                                    {new Date(session.created_at).toLocaleString()}
                                                                 </span>
                                                                {showQueryBelow && (
                                                                    <span className="text-xs text-muted-foreground truncate max-w-[280px] mt-0.5">
                                                                        {session.latest_task_query}
                                                                    </span>
                                                                )}
                                                            </div>
                                                            </>
                                                        );
                                                    })()}
                                                </div>
                                            </td>
                                            <td className="p-4 align-middle [&:has([role=checkbox])]:pr-0 hidden md:table-cell">
                                                <TooltipProvider>
                                                    <Tooltip>
                                                        <TooltipTrigger asChild>
                                                            <div className="flex items-center justify-center size-8 rounded-full cursor-default hover:bg-muted transition-colors">
                                                                {session.first_task_mode === "card_template" || session.is_research_session ? (
                                                                    <Microscope className="size-5 text-violet-500" />
                                                                ) : (
                                                                    <Sparkles className="size-5 text-amber-500" />
                                                                )}
                                                            </div>
                                                        </TooltipTrigger>
                                                        <TooltipContent suppressHydrationWarning>
                                                            <p>{session.first_task_mode === "card_template" || session.is_research_session ? t("runs.deepResearch") : t("runs.everyday")}</p>
                                                        </TooltipContent>
                                                    </Tooltip>
                                                </TooltipProvider>
                                            </td>
                                            <td className="p-4 align-middle [&:has([role=checkbox])]:pr-0 hidden sm:table-cell">
                                                <TooltipProvider>
                                                    <Tooltip>
                                                        <TooltipTrigger asChild>
                                                            <div className="flex items-center gap-2 cursor-default">
                                                                <Layers className="size-4 text-muted-foreground" />
                                                                <span>{session.task_count}</span>
                                                            </div>
                                                        </TooltipTrigger>
                                                        <TooltipContent suppressHydrationWarning>
                                                            <div className="flex flex-col gap-1">
                                                                <div className="flex items-center gap-1.5">
                                                                    <CheckCircle2 className="size-3 text-emerald-500" />
                                                                    <span>{session.successful_tasks || 0} {t("runs.successful")}</span>
                                                                </div>
                                                                {(session.failed_tasks || 0) > 0 && (
                                                                    <div className="flex items-center gap-1.5">
                                                                        <XCircle className="size-3 text-red-500" />
                                                                        <span>{session.failed_tasks} {t("runs.failed")}</span>
                                                                    </div>
                                                                )}
                                                            </div>
                                                        </TooltipContent>
                                                    </Tooltip>
                                                </TooltipProvider>
                                            </td>
                                            <td className="p-4 align-middle [&:has([role=checkbox])]:pr-0 hidden sm:table-cell">
                                                <TooltipProvider>
                                                    <Tooltip>
                                                        <TooltipTrigger asChild>
                                                            <div className="flex items-center gap-2 cursor-default">
                                                                <DollarSign className="size-4 text-muted-foreground" />
                                                                <span>${(session.total_cost_usd || 0).toFixed(3)}</span>
                                                            </div>
                                                        </TooltipTrigger>
                                                        <TooltipContent suppressHydrationWarning>
                                                            <div className="flex flex-col gap-1 text-xs">
                                                                <span>{t("runs.tokens", { count: session.tokens_used })}</span>
                                                                {session.average_cost_per_task !== undefined && session.average_cost_per_task > 0 && (
                                                                    <span>{t("runs.avgPerTask", { amount: session.average_cost_per_task.toFixed(3) })}</span>
                                                                )}
                                                            </div>
                                                        </TooltipContent>
                                                    </Tooltip>
                                                </TooltipProvider>
                                            </td>
                                            <td className="p-4 align-middle [&:has([role=checkbox])]:pr-0 text-right">
                                                <div className="flex items-center justify-end gap-2">
                                                    <DropdownMenu>
                                                        <DropdownMenuTrigger asChild>
                                                            <Button
                                                                variant="ghost"
                                                                size="icon"
                                                                className="size-8"
                                                                aria-label={t("sidebar.editTitle")}
                                                            >
                                                                <MoreHorizontal className="size-4" />
                                                            </Button>
                                                        </DropdownMenuTrigger>
                                                        <DropdownMenuContent align="end" className="w-40">
                                                            <DropdownMenuItem onClick={() => handleEditTitle(session)}>
                                                                <Pencil className="size-4" />
                                                                {t("sidebar.editTitle")}
                                                            </DropdownMenuItem>
                                                            <DropdownMenuItem onClick={() => handleTogglePin(session)}>
                                                                <Pin className="size-4" />
                                                                {session.pinned ? t("common.unpin") : t("common.pin")}
                                                            </DropdownMenuItem>
                                                            <DropdownMenuSeparator />
                                                            <DropdownMenuItem onClick={() => handleDeleteSession(session)} className="text-red-600">
                                                                <Trash2 className="size-4" />
                                                                {t("common.delete")}
                                                            </DropdownMenuItem>
                                                        </DropdownMenuContent>
                                                    </DropdownMenu>
                                                    <Button variant="ghost" size="sm" asChild>
                                                    <Link
                                                        href={`/run-detail?session_id=${session.session_id}`}
                                                        onClick={(event) => {
                                                            if (currentSessionId === session.session_id) {
                                                                event.preventDefault();
                                                            }
                                                        }}
                                                    >
                                                        <MessageSquare className="size-4 mr-2" />
                                                        {t("common.view")}
                                                    </Link>
                                                </Button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))
                                )}
                            </tbody>
                        </table>
                    </div>
                    {totalCount !== null && (
                        <div className="flex items-center justify-between px-4 py-2 border-t text-xs text-muted-foreground">
                            <span>
                                {t("runs.showing", { count: sessions.length, total: totalCount })}
                            </span>
                            {sessions.length < totalCount && (
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => void sessionsQuery.fetchNextPage()}
                                    disabled={isLoadingMore}
                                >
                                    {isLoadingMore && (
                                        <Loader2 className="mr-2 size-3 animate-spin" />
                                    )}
                                    {t("runs.loadMore")}
                                </Button>
                            )}
                        </div>
                    )}
                </div>
            )}
            <Dialog open={!!editingSession} onOpenChange={(open) => !open && setEditingSession(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>{t("sidebar.editTitleDialog")}</DialogTitle>
                    </DialogHeader>
                    <Input
                        value={editingTitle}
                        onChange={(e) => setEditingTitle(e.target.value)}
                        placeholder={t("sidebar.editTitlePlaceholder")}
                        aria-label={t("sidebar.editTitle")}
                        name="session-title"
                        autoComplete="off"
                    />
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setEditingSession(null)}>{t("common.cancel")}</Button>
                        <Button onClick={handleSaveTitle}>{t("common.save")}</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}

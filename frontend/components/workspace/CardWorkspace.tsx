"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import useSWRInfinite from "swr/infinite";
import { useDispatch, useSelector } from "react-redux";
import { RootState } from "@/lib/store";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sparkles, User, Layers, Brain, CheckCircle2, Clock, FileText, Maximize2, Minimize2, X, LayoutGrid, List, SlidersHorizontal, Lock, Unlock, Download } from "lucide-react";
import { cn } from "@/lib/utils";
import { bulkUpdateStatus, updateCardModel, updateCardStatus, CardData } from "@/lib/features/runSlice";
import { bulkUpdateCardModel, bulkUpdateCardStatus, createApkgExport, getApkgExport, getApkgExportDownloadUrl, ApkgExportRecord } from "@/lib/kardcraft/api";
import { getSessionWorkspace } from "@/lib/kardcraft/session-repository";

export function CardWorkspace({
    sessionId,
    workspacePhase = "idle",
    isFullscreen = false,
    onToggleFullscreen,
    onClose,
}: {
    sessionId?: string | null;
    workspacePhase?: "idle" | "clearing" | "loading" | "hydrated" | "empty" | "error";
    isFullscreen?: boolean;
    onToggleFullscreen?: () => void;
    onClose?: () => void;
}) {
    const { t } = useTranslation();
    const cards = useSelector((state: RootState) => state.run.cards);
    const cardsVersion = useSelector((state: RootState) => state.run.cardsVersion);
    const templatePreflight = useSelector((state: RootState) => state.run.templatePreflight);
    const dispatch = useDispatch();
    const [activeTab, setActiveTab] = useState<"all" | "draft" | "active" | "confirmed">("all");
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [selectedTemplate, setSelectedTemplate] = useState<string>("");
    const [searchTerm, setSearchTerm] = useState<string>("");
    const [viewMode, setViewMode] = useState<"list" | "grid">("list");
    const [density, setDensity] = useState<"comfortable" | "compact">("comfortable");
    const [inspectorOpen, setInspectorOpen] = useState(false);
    const [headerPinned, setHeaderPinned] = useState(false);
    const [headerHover, setHeaderHover] = useState(false);
    const [exportTask, setExportTask] = useState<ApkgExportRecord | null>(null);
    const [exporting, setExporting] = useState(false);
    const [exportError, setExportError] = useState("");
    const exportNotFoundRetriesRef = useRef(0);
    const [resolvedTemplateProfiles, setResolvedTemplateProfiles] = useState<string[]>([]);
    const PAGE_SIZE = 20;
    const VIRTUAL_THRESHOLD = 50;
    const ESTIMATED_ROW_HEIGHT = 220;
    const OVERSCAN = 6;
    const containerRef = useRef<HTMLDivElement | null>(null);
    const [scrollTop, setScrollTop] = useState(0);
    const [containerHeight, setContainerHeight] = useState(0);
    const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 focus-visible:ring-offset-background";

    const templateOptions = useMemo(() => {
        return resolvedTemplateProfiles.map((id) => ({ id, label: id }));
    }, [resolvedTemplateProfiles]);

    const statusCounts = useMemo(() => {
        let draft = 0;
        let active = 0;
        let confirmed = 0;
        for (const card of cards) {
            if (card.edit_state.status === "confirmed") {
                confirmed += 1;
            } else if (card.edit_state.status === "draft") {
                draft += 1;
            } else {
                active += 1;
            }
        }
        return { draft, active, confirmed, total: cards.length };
    }, [cards]);

    const filteredCards = useMemo(() => {
        let scoped = cards;
        if (activeTab === "draft") scoped = cards.filter(card => card.edit_state.status === "draft");
        if (activeTab === "confirmed") scoped = cards.filter(card => card.edit_state.status === "confirmed");
        if (activeTab === "active") scoped = cards.filter(card => card.edit_state.status === "ai_editing" || card.edit_state.status === "user_editing");
        if (!searchTerm.trim()) return scoped;
        const keyword = searchTerm.toLowerCase();
        return scoped.filter(card => {
            const front = card.content.data.front?.toLowerCase() || "";
            const back = card.content.data.back?.toLowerCase() || "";
            return front.includes(keyword) || back.includes(keyword);
        });
    }, [activeTab, cards, searchTerm]);

    const cardsSignature = useMemo(() => {
        return `${cardsVersion}:${cards.length}`;
    }, [cardsVersion, cards.length]);

    const getKey = useCallback((pageIndex: number, previousPageData: typeof filteredCards | null) => {
        if (!sessionId) return null;
        if (previousPageData && previousPageData.length < PAGE_SIZE) return null;
        return ["workspace-cards", sessionId, activeTab, searchTerm, cardsSignature, pageIndex];
    }, [sessionId, activeTab, searchTerm, cardsSignature]);

    const fetcher = useCallback(async (key: readonly [string, string, string, string, string, number]) => {
        const pageIndex = key[5];
        const start = pageIndex * PAGE_SIZE;
        return filteredCards.slice(start, start + PAGE_SIZE);
    }, [filteredCards]);

    const { data: pagedCards, size, setSize, isValidating } = useSWRInfinite(
        getKey,
        fetcher,
        {
            keepPreviousData: true,
            revalidateOnFocus: false,
        }
    );

    const visibleCards = useMemo(() => {
        if (!pagedCards) return filteredCards.slice(0, PAGE_SIZE);
        return pagedCards.flat();
    }, [pagedCards, filteredCards]);

    const virtualEnabled = visibleCards.length > VIRTUAL_THRESHOLD;
    const totalHeight = virtualEnabled ? visibleCards.length * ESTIMATED_ROW_HEIGHT : 0;
    const startIndex = virtualEnabled
        ? Math.max(0, Math.floor(scrollTop / ESTIMATED_ROW_HEIGHT) - OVERSCAN)
        : 0;
    const endIndex = virtualEnabled
        ? Math.min(
            visibleCards.length,
            Math.ceil((scrollTop + containerHeight) / ESTIMATED_ROW_HEIGHT) + OVERSCAN
        )
        : visibleCards.length;
    const renderCards = virtualEnabled ? visibleCards.slice(startIndex, endIndex) : visibleCards;
    const offsetY = virtualEnabled ? startIndex * ESTIMATED_ROW_HEIGHT : 0;

    const selectedCard = useMemo(() => {
        if (!selectedId) return null;
        return cards.find(card => card.card_id === selectedId) || null;
    }, [cards, selectedId]);

    useEffect(() => {
        let cancelled = false;
        const run = async () => {
            if (!sessionId) {
                setResolvedTemplateProfiles([]);
                return;
            }
            try {
                const workspace = await getSessionWorkspace(sessionId);
                if (cancelled) return;
                const supported = Array.isArray(workspace.supported_question_types)
                    ? workspace.supported_question_types.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
                    : [];
                setResolvedTemplateProfiles(supported);
            } catch {
                if (!cancelled) setResolvedTemplateProfiles([]);
                return;
            }
        };
        void run();
        return () => {
            cancelled = true;
        };
    }, [sessionId, cardsVersion]);

    useEffect(() => {
        if (!selectedCard || selectedTemplate) return;
        if (templateOptions.length === 0) return;
        const model = String(selectedCard.suggested_question_type || selectedCard.content.model || "").trim();
        const isKnown = templateOptions.some((option) => option.id === model);
        if (isKnown) {
            setSelectedTemplate(model);
        }
    }, [selectedCard, selectedTemplate, templateOptions]);

    const handleSelect = useCallback((cardId: string) => {
        setSelectedId(cardId);
        const card = cards.find((item) => item.card_id === cardId);
        const model = String(card?.suggested_question_type || card?.content?.model || "").trim();
        const isKnownQuestionType = templateOptions.some((option) => option.id === model);
        setSelectedTemplate(isKnownQuestionType ? model : "");
        setInspectorOpen(true);
    }, [cards, templateOptions]);

    const handleTab = useCallback((tab: "all" | "draft" | "active" | "confirmed") => {
        setActiveTab(tab);
    }, []);

    const handleApproveAll = useCallback(async () => {
        const ids = filteredCards.map(card => card.card_id);
        if (!ids.length) return;
        dispatch(bulkUpdateStatus({ card_ids: ids, status: "confirmed" }));
        try {
            if (sessionId) {
                await bulkUpdateCardStatus(sessionId, ids, "confirmed");
            }
        } catch (err) {
            console.warn("[Workspace] Failed to persist approve all:", err);
        }
    }, [dispatch, filteredCards, sessionId]);

    const handleApplyQuestionType = useCallback(async () => {
        if (!selectedCard || !selectedTemplate) return;
        dispatch(updateCardModel({ card_id: selectedCard.card_id, model: selectedTemplate }));
        try {
            if (sessionId) {
                await bulkUpdateCardModel(sessionId, [selectedCard.card_id], selectedTemplate);
            }
        } catch (err) {
            console.warn("[Workspace] Failed to persist question type update:", err);
        }
    }, [dispatch, selectedCard, selectedTemplate, sessionId]);

    const handleConfirmSelected = useCallback(async () => {
        if (!selectedCard) return;
        dispatch(updateCardStatus({ card_id: selectedCard.card_id, status: "confirmed" }));
        try {
            if (sessionId) {
                await bulkUpdateCardStatus(sessionId, [selectedCard.card_id], "confirmed");
            }
        } catch (err) {
            console.warn("[Workspace] Failed to persist confirm:", err);
        }
    }, [dispatch, selectedCard, sessionId]);

    const handleRevertSelected = useCallback(async () => {
        if (!selectedCard) return;
        dispatch(updateCardStatus({ card_id: selectedCard.card_id, status: "draft" }));
        try {
            if (sessionId) {
                await bulkUpdateCardStatus(sessionId, [selectedCard.card_id], "draft");
            }
        } catch (err) {
            console.warn("[Workspace] Failed to persist revert:", err);
        }
    }, [dispatch, selectedCard, sessionId]);

    const handleExportApkg = useCallback(async () => {
        if (!sessionId || exporting) return;
        setExportError("");
        setExporting(true);
        exportNotFoundRetriesRef.current = 0;
        try {
            const created = await createApkgExport({
                session_id: sessionId,
                template_id: templatePreflight.templateId || undefined,
            });
            setExportTask(created);
        } catch (err) {
            setExportError(err instanceof Error ? err.message : "Failed to export apkg");
        } finally {
            setExporting(false);
        }
    }, [exporting, sessionId, templatePreflight.templateId]);

    const handleDownloadApkg = useCallback(() => {
        if (!exportTask?.export_id || exportTask.status !== "completed") return;
        const exportSessionId = exportTask.session_id || sessionId;
        if (!exportSessionId) return;
        window.location.href = getApkgExportDownloadUrl(exportSessionId, exportTask.export_id);
    }, [exportTask, sessionId]);

    useEffect(() => {
        const exportSessionId = exportTask?.session_id || sessionId;
        if (!exportSessionId || !exportTask?.export_id || exportTask.status !== "processing") return;
        let cancelled = false;
        const timer = window.setInterval(async () => {
            try {
                const latest = await getApkgExport(exportSessionId, exportTask.export_id);
                if (!cancelled) {
                    exportNotFoundRetriesRef.current = 0;
                    setExportTask(latest);
                }
            } catch (err) {
                if (!cancelled) {
                    const msg = err instanceof Error ? err.message : "Failed to query export task";
                    if (msg.includes("export task not found") && exportNotFoundRetriesRef.current < 8) {
                        exportNotFoundRetriesRef.current += 1;
                        return;
                    }
                    setExportError(err instanceof Error ? err.message : "Failed to query export task");
                }
            }
        }, 2000);
        return () => {
            cancelled = true;
            window.clearInterval(timer);
        };
    }, [exportTask?.export_id, exportTask?.session_id, exportTask?.status, sessionId]);

    useEffect(() => {
        setSize(1);
    }, [activeTab, searchTerm, cardsSignature, setSize]);

    useEffect(() => {
        if (!selectedTemplate) return;
        const valid = templateOptions.some((option) => option.id === selectedTemplate);
        if (!valid) {
            setSelectedTemplate("");
        }
    }, [selectedTemplate, templateOptions]);

    const cardPadding = density === "compact" ? "p-2.5 pt-1.5" : "p-3 pt-2";
    const cardText = density === "compact" ? "text-[11px]" : "text-xs";
    const cardFrontPadding = density === "compact" ? "p-2" : "p-2.5";
    const cardBackPadding = density === "compact" ? "p-2" : "p-2.5";

    const renderCard = (card: CardData) => (
        <Card
            key={card.card_id}
            className={cn(
                "group transition-all duration-300 border-l-4 overflow-hidden relative cursor-pointer bg-[var(--app-surface-1)] hover:bg-[var(--app-surface-2)]",
                card.edit_state.status === "ai_editing"
                    ? "border-l-blue-500 ring-1 ring-blue-500/15"
                    : card.edit_state.status === "user_editing"
                        ? "border-l-amber-500"
                        : card.edit_state.status === "confirmed"
                            ? "border-l-emerald-500"
                            : "border-l-muted hover:border-l-blue-400/50 hover:shadow-lg"
            )}
            onClick={() => handleSelect(card.card_id)}
            style={{ contentVisibility: "auto", containIntrinsicSize: "1px 220px" }}
        >
            {card.edit_state.status === "ai_editing" && (
                <div className="absolute top-0 right-0 p-1 opacity-20">
                    <Sparkles className="w-3 h-3 text-blue-500 animate-spin-slow" />
                </div>
            )}
            <CardHeader className="p-3 pb-0 space-y-0">
                <div className="flex items-center justify-between">
                    <span className="text-[10px] font-mono text-muted-foreground/70 uppercase tracking-tighter">
                        V{card.content.version} • {card.card_id.slice(-6)}
                    </span>
                    {card.edit_state.status !== "draft" && card.edit_state.locked_by && (
                        <Badge
                            variant="secondary"
                            className={cn(
                                "text-[9px] px-1.5 py-0 rounded flex items-center gap-1",
                                card.edit_state.status === "ai_editing"
                                    ? "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
                                    : "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300"
                            )}
                        >
                            {card.edit_state.status === "ai_editing"
                                ? <><Sparkles className="w-2.5 h-2.5" /> {t("workspace.aiOptimizing")}</>
                                : <><User className="w-2.5 h-2.5" /> {t("workspace.userEditing")}</>}
                        </Badge>
                    )}
                </div>
            </CardHeader>
            <CardContent className={cn(cardPadding, "space-y-2.5")}>
                <div className="space-y-1">
                    <span className="text-[9px] font-bold text-muted-foreground/50 uppercase tracking-widest block">{t("workspace.frontLabel")}</span>
                    <div className={cn(cardFrontPadding, "rounded-lg bg-[var(--app-surface-2)] border border-[var(--app-border-subtle)] font-medium leading-relaxed group-hover:bg-[var(--app-surface-3)] transition-colors", cardText)}>
                        {card.content.data.front}
                    </div>
                </div>
                <div className="space-y-1">
                    <span className="text-[9px] font-bold text-muted-foreground/50 uppercase tracking-widest block">{t("workspace.backLabel")}</span>
                    <div className={cn(cardBackPadding, "rounded-lg bg-[var(--app-surface-3)] border border-[var(--app-border-subtle)] italic text-foreground/90 leading-relaxed", cardText)}>
                        {card.content.data.back}
                    </div>
                </div>
            </CardContent>
        </Card>
    );

    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;

        const handleScroll = () => {
            setScrollTop(container.scrollTop);
        };

        const resizeObserver = new ResizeObserver((entries) => {
            const entry = entries[0];
            if (entry) {
                setContainerHeight(entry.contentRect.height);
            }
        });

        resizeObserver.observe(container);
        setContainerHeight(container.clientHeight);
        container.addEventListener("scroll", handleScroll, { passive: true });

        return () => {
            resizeObserver.disconnect();
            container.removeEventListener("scroll", handleScroll);
        };
    }, []);

    const isWorkspaceLoading = workspacePhase === "clearing" || workspacePhase === "loading";
    const isWorkspaceEmpty = workspacePhase === "empty";

    if (isWorkspaceLoading) {
        return (
            <div className="flex flex-col h-full p-4 bg-background border-l">
                <div className="h-10 w-full rounded-md bg-muted animate-pulse mb-3" />
                <div className="grid grid-cols-4 gap-2 mb-4">
                    <div className="h-7 rounded-md bg-muted animate-pulse" />
                    <div className="h-7 rounded-md bg-muted animate-pulse" />
                    <div className="h-7 rounded-md bg-muted animate-pulse" />
                    <div className="h-7 rounded-md bg-muted animate-pulse" />
                </div>
                <div className="h-8 w-full rounded-md bg-muted animate-pulse mb-4" />
                <div className="space-y-3">
                    <div className="h-16 rounded-lg bg-muted animate-pulse" />
                    <div className="h-16 rounded-lg bg-muted animate-pulse" />
                    <div className="h-16 rounded-lg bg-muted animate-pulse" />
                </div>
            </div>
        );
    }

    if (workspacePhase === "error") {
        return (
            <div className="flex flex-col items-center justify-center h-full p-8 text-center text-muted-foreground bg-[var(--app-surface-1)]">
                <h3 className="text-lg font-medium text-foreground/80 mb-2">{t("workspace.errorTitle")}</h3>
                <p className="text-sm max-w-[240px]">{t("workspace.errorDesc")}</p>
                <button
                    type="button"
                    className={cn(
                        "mt-4 text-xs font-semibold uppercase tracking-widest border rounded-md px-3 py-2 bg-[var(--app-surface-1)] hover:bg-[var(--app-surface-2)] transition-colors border-[var(--app-border-subtle)]",
                        focusRing
                    )}
                    onClick={() => window.location.reload()}
                >
                    {t("common.retry")}
                </button>
            </div>
        );
    }

    if (cards.length === 0 && (isWorkspaceEmpty || workspacePhase === "idle")) {
        return (
            <div className="flex flex-col items-center justify-center h-full w-full p-8 text-center text-muted-foreground bg-[var(--app-surface-1)] animate-in fade-in duration-500">
                <div className="relative mb-6">
                    <Layers className="w-16 h-16 opacity-10" />
                    <Brain className="w-8 h-8 absolute -bottom-2 -right-2 text-blue-500/20 animate-pulse" />
                </div>
                <h3 className="text-lg font-medium text-foreground/80 mb-2">{t("workspace.emptyTitle")}</h3>
                <p className="text-sm max-w-[200px]">{t("workspace.emptyDesc")}</p>
            </div>
        );
    }

    const showHeader = !isFullscreen || headerPinned || headerHover;

    return (
        <div className={cn(
            "flex flex-col h-full w-full overflow-hidden bg-[var(--app-surface-1)] border-[var(--app-border-subtle)] shadow-[0_12px_30px_-24px_rgba(0,0,0,0.45)] animate-in slide-in-from-right duration-500",
            isFullscreen ? "border-none rounded-none relative" : "border-l"
        )}>
            {isFullscreen && (
                <div
                    className="absolute left-0 top-0 h-6 w-full z-30"
                    onMouseEnter={() => setHeaderHover(true)}
                    onMouseLeave={() => {
                        if (!headerPinned) setHeaderHover(false);
                    }}
                />
            )}
            <div className={cn(
                "p-4 border-b border-[var(--app-border-subtle)] bg-[var(--app-surface-2)] backdrop-blur-md sticky top-0 z-20 transition-all duration-300 ease-out",
                isFullscreen && "px-6",
                !showHeader && "max-h-0 opacity-0 pointer-events-none py-0 border-transparent overflow-hidden"
            )}
                onMouseEnter={() => setHeaderHover(true)}
                onMouseLeave={() => {
                    if (!headerPinned && isFullscreen) setHeaderHover(false);
                }}
            >
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <div className="p-1.5 rounded-lg bg-blue-500/10">
                            <Layers className="w-4 h-4 text-blue-600 dark:text-blue-400" />
                        </div>
                        <div>
                            <h3 className="text-sm font-semibold leading-none">{t("workspace.headerTitle")}</h3>
                            <p className="text-[10px] text-muted-foreground mt-0.5 uppercase tracking-wide">{t("workspace.headerSubtitle")}</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <Badge variant="outline" className="font-mono text-[10px] bg-[var(--app-surface-1)] border-[var(--app-border-subtle)]">
                            {t("workspace.cardsLabel", { count: statusCounts.total })}
                        </Badge>
                        {selectedCard && (
                            <Button
                                type="button"
                                variant={inspectorOpen ? "secondary" : "ghost"}
                                size="icon"
                                className="h-7 w-7"
                                onClick={() => setInspectorOpen(!inspectorOpen)}
                                aria-label={t("workspace.toggleInspector")}
                            >
                                <FileText className="h-4 w-4" />
                            </Button>
                        )}
                        {isFullscreen && (
                            <Button
                                type="button"
                                variant={headerPinned ? "secondary" : "ghost"}
                                size="icon"
                                className="h-7 w-7"
                                onClick={() => setHeaderPinned(!headerPinned)}
                                aria-label={headerPinned ? t("workspace.unlockHeader") : t("workspace.lockHeader")}
                            >
                                {headerPinned ? <Lock className="h-4 w-4" /> : <Unlock className="h-4 w-4" />}
                            </Button>
                        )}
                        {onToggleFullscreen && (
                            <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7"
                                onClick={onToggleFullscreen}
                                aria-label={isFullscreen ? t("runDetail.collapseWorkspace") : t("runDetail.expandWorkspace")}
                            >
                                {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
                            </Button>
                        )}
                        {onClose && (
                            <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7"
                                onClick={onClose}
                                aria-label={t("runDetail.closeWorkspace")}
                            >
                                <X className="h-4 w-4" />
                            </Button>
                        )}
                    </div>
                </div>
                {templatePreflight.status !== "idle" && (
                    <div
                        className={cn(
                            "mt-2 text-[11px] rounded-md border px-2 py-1 flex items-center justify-between gap-2",
                            templatePreflight.status === "passed" && "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300",
                            templatePreflight.status === "failed" && "border-red-200 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300",
                            templatePreflight.status === "running" && "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-300",
                        )}
                    >
                        <div className="min-w-0">
                            <div className="truncate">
                                {templatePreflight.message || "Template precheck"}
                            </div>
                            <div className="mt-0.5 text-[10px] opacity-80 truncate font-mono">
                                {templatePreflight.templateId || "template"}@v{templatePreflight.templateVersion ?? "?"}
                                {templatePreflight.checkedAt ? ` • ${new Date(templatePreflight.checkedAt).toLocaleTimeString()}` : ""}
                            </div>
                        </div>
                        <div className="shrink-0 flex items-center gap-2">
                            {templatePreflight.cardCount !== null && (
                                <span className="font-mono">
                                    ~{templatePreflight.cardCount}
                                </span>
                            )}
                        </div>
                    </div>
                )}
                <div className="mt-3 grid grid-cols-4 gap-2 text-[10px] font-medium">
                    <button
                        className={cn(
                            "rounded-md border px-2 py-1 transition-colors border-[var(--app-border-subtle)]",
                            focusRing,
                            activeTab === "all" ? "bg-[var(--app-accent-soft)] text-[var(--app-accent-foreground)]" : "bg-[var(--app-surface-1)] text-muted-foreground"
                        )}
                        onClick={() => handleTab("all")}
                        type="button"
                    >
                        {t("workspace.tabAll")} {statusCounts.total}
                    </button>
                    <button
                        className={cn(
                            "rounded-md border px-2 py-1 transition-colors border-[var(--app-border-subtle)]",
                            focusRing,
                            activeTab === "draft" ? "bg-[var(--app-accent-soft)] text-[var(--app-accent-foreground)]" : "bg-[var(--app-surface-1)] text-muted-foreground"
                        )}
                        onClick={() => handleTab("draft")}
                        type="button"
                    >
                        {t("workspace.tabDraft")} {statusCounts.draft}
                    </button>
                    <button
                        className={cn(
                            "rounded-md border px-2 py-1 transition-colors border-[var(--app-border-subtle)]",
                            focusRing,
                            activeTab === "active" ? "bg-[var(--app-accent-soft)] text-[var(--app-accent-foreground)]" : "bg-[var(--app-surface-1)] text-muted-foreground"
                        )}
                        onClick={() => handleTab("active")}
                        type="button"
                    >
                        {t("workspace.tabActive")} {statusCounts.active}
                    </button>
                    <button
                        className={cn(
                            "rounded-md border px-2 py-1 transition-colors border-[var(--app-border-subtle)]",
                            focusRing,
                            activeTab === "confirmed" ? "bg-[var(--app-accent-soft)] text-[var(--app-accent-foreground)]" : "bg-[var(--app-surface-1)] text-muted-foreground"
                        )}
                        onClick={() => handleTab("confirmed")}
                        type="button"
                    >
                        {t("workspace.tabConfirmed")} {statusCounts.confirmed}
                    </button>
                </div>
                <div className="mt-3">
                    <input
                        className="w-full text-xs rounded-md border bg-[var(--app-surface-1)] px-2 py-1.5 border-[var(--app-border-subtle)]"
                        placeholder={t("workspace.searchPlaceholder")}
                        aria-label={t("workspace.searchPlaceholder")}
                        name="workspace-search"
                        autoComplete="off"
                        value={searchTerm}
                        onChange={(event) => setSearchTerm(event.target.value)}
                    />
                </div>
                <div className="mt-3 flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
                    <div className="flex items-center gap-1">
                        <Button
                            type="button"
                            variant={viewMode === "list" ? "secondary" : "ghost"}
                            size="icon"
                            className="h-6 w-6"
                            aria-label={t("workspace.viewList")}
                            onClick={() => setViewMode("list")}
                        >
                            <List className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                            type="button"
                            variant={viewMode === "grid" ? "secondary" : "ghost"}
                            size="icon"
                            className="h-6 w-6"
                            aria-label={t("workspace.viewGrid")}
                            onClick={() => setViewMode("grid")}
                        >
                            <LayoutGrid className="h-3.5 w-3.5" />
                        </Button>
                    </div>
                    <div className="flex items-center gap-1">
                        <SlidersHorizontal className="h-3.5 w-3.5" />
                        <Button
                            type="button"
                            variant={density === "compact" ? "secondary" : "ghost"}
                            size="sm"
                            className="h-6 px-2 text-[10px]"
                            aria-label={t("workspace.densityCompact")}
                            onClick={() => setDensity("compact")}
                        >
                            {t("workspace.densityCompact")}
                        </Button>
                        <Button
                            type="button"
                            variant={density === "comfortable" ? "secondary" : "ghost"}
                            size="sm"
                            className="h-6 px-2 text-[10px]"
                            aria-label={t("workspace.densityComfortable")}
                            onClick={() => setDensity("comfortable")}
                        >
                            {t("workspace.densityComfortable")}
                        </Button>
                    </div>
                </div>
            </div>
            {isFullscreen ? (
                <div className="flex-1 flex flex-col overflow-hidden">
                    <div
                        className={cn(
                            "flex-1 w-full grid gap-6 px-6 py-4 overflow-hidden",
                            inspectorOpen && selectedCard
                                ? "max-w-[1280px] mx-auto grid-cols-[minmax(0,1fr)_320px]"
                                : "grid-cols-1"
                        )}
                    >
                        <div ref={containerRef} className="h-full overflow-y-auto custom-scrollbar pr-1">
                            {filteredCards.length === 0 && workspacePhase !== "loading" && (
                                <div className="flex flex-col items-center justify-center h-[260px] text-center text-muted-foreground bg-[var(--app-surface-2)]/60 border border-[var(--app-border-subtle)] rounded-lg">
                                    <div className="text-sm font-medium text-foreground/80">{t("workspace.filterEmptyTitle")}</div>
                                    <div className="text-xs mt-1 max-w-[320px]">{t("workspace.filterEmptyDesc")}</div>
                                </div>
                            )}
                            {viewMode === "grid" ? (
                                <div className={cn(
                                    "grid gap-4",
                                    density === "compact" ? "sm:grid-cols-2 xl:grid-cols-3" : "sm:grid-cols-2 xl:grid-cols-2 2xl:grid-cols-3"
                                )}>
                                    {visibleCards.map((card) => renderCard(card))}
                                </div>
                            ) : (
                                <>
                                    {virtualEnabled ? (
                                        <div style={{ height: totalHeight, position: "relative" }}>
                                            <div style={{ transform: `translateY(${offsetY}px)` }} className="space-y-4">
                                                {renderCards.map((card) => renderCard(card))}
                                            </div>
                                        </div>
                                    ) : (
                                        <div className="space-y-4">
                                            {visibleCards.map((card) => renderCard(card))}
                                        </div>
                                    )}
                                </>
                            )}
                            {filteredCards.length > visibleCards.length && (
                                <button
                                    className={cn(
                                        "mt-4 w-full text-xs uppercase tracking-[0.2em] font-semibold border rounded-md py-2 bg-[var(--app-surface-1)] hover:bg-[var(--app-surface-2)] transition-colors border-[var(--app-border-subtle)]",
                                        focusRing
                                    )}
                                    type="button"
                                    onClick={() => setSize(size + 1)}
                                    disabled={isValidating}
                                >
                                    {isValidating
                                        ? t("workspace.loading")
                                        : t("workspace.loadMore", { count: filteredCards.length - visibleCards.length })}
                                </button>
                            )}
                        </div>
                        {inspectorOpen && selectedCard && (
                        <div className="h-full overflow-y-auto space-y-4 border-l border-[var(--app-border-subtle)] pl-4">
                            <div className="space-y-3">
                                <div className="grid grid-cols-1 gap-2">
                                    <button
                                        className={cn(
                                            "text-[10px] font-semibold uppercase tracking-widest border rounded-md px-2 py-2 bg-[var(--app-surface-1)] hover:bg-[var(--app-surface-2)] transition-colors border-[var(--app-border-subtle)]",
                                            focusRing
                                        )}
                                        type="button"
                                        disabled={statusCounts.total === 0}
                                        onClick={handleApproveAll}
                                    >
                                        {t("workspace.approveAll")}
                                    </button>
                                    <button
                                        className={cn(
                                            "text-[10px] font-semibold uppercase tracking-widest border rounded-md px-2 py-2 bg-[var(--app-surface-1)] hover:bg-[var(--app-surface-2)] transition-colors border-[var(--app-border-subtle)]",
                                            focusRing
                                        )}
                                        type="button"
                                        disabled={!selectedCard || !selectedTemplate}
                                        onClick={handleApplyQuestionType}
                                    >
                                        {t("workspace.applyQuestionType")}
                                    </button>
                                    <button
                                        className={cn(
                                            "text-[10px] font-semibold uppercase tracking-widest border rounded-md px-2 py-2 bg-[var(--app-surface-1)] hover:bg-[var(--app-surface-2)] transition-colors border-[var(--app-border-subtle)] inline-flex items-center justify-center gap-1.5",
                                            focusRing
                                        )}
                                        type="button"
                                        disabled={statusCounts.confirmed === 0 || exporting}
                                        onClick={handleExportApkg}
                                    >
                                        <Download className="w-3 h-3" />
                                        {exporting || exportTask?.status === "processing" ? t("workspace.exportingApkg") : t("workspace.exportApkg")}
                                    </button>
                                </div>
                                {(exportTask || exportError) && (
                                    <div className="text-[10px] text-muted-foreground break-all">
                                        {exportError
                                            ? exportError
                                            : exportTask?.status === "completed"
                                                ? `${t("workspace.exportReady")} ${exportTask.file_name || ""}`
                                                : exportTask?.status === "failed"
                                                    ? `${t("workspace.exportFailed")} ${exportTask.error || ""}`
                                                    : t("workspace.exportingApkg")}
                                        {exportTask?.status === "completed" && (
                                            <button
                                                type="button"
                                                className={cn("ml-1 underline underline-offset-2 text-[var(--app-accent-foreground)]", focusRing)}
                                                onClick={handleDownloadApkg}
                                            >
                                                {t("workspace.downloadApkg")}
                                            </button>
                                        )}
                                    </div>
                                )}
                            </div>
                            {selectedCard ? (
                                <div className="space-y-2">
                                    <div className="flex items-center justify-between">
                                        <div className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">{t("workspace.inspector")}</div>
                                        <Badge variant="outline" className="text-[9px] font-mono">
                                            {selectedCard.suggested_question_type || selectedCard.content.model}
                                        </Badge>
                                    </div>
                                    <div className="text-xs font-semibold flex items-center gap-2">
                                        <FileText className="w-3.5 h-3.5 text-muted-foreground" />
                                        {selectedCard.content.data.front.slice(0, 80)}
                                    </div>
                                    <div className="space-y-1">
                                        <div className="text-[9px] uppercase tracking-[0.2em] text-muted-foreground">{t("workspace.questionTypeLabel")}</div>
                                        <select
                                            className={cn(
                                                "w-full text-xs rounded-md border bg-[var(--app-surface-1)] px-2 py-1.5 border-[var(--app-border-subtle)]",
                                                focusRing
                                            )}
                                            disabled={templateOptions.length === 0}
                                            value={selectedTemplate}
                                            onChange={(event) => setSelectedTemplate(event.target.value)}
                                        >
                                            {templateOptions.map((option) => (
                                                <option key={option.id} value={option.id}>
                                                    {option.label}
                                                </option>
                                            ))}
                                        </select>
                                    </div>
                                    <div className="grid grid-cols-2 gap-2">
                                        <button
                                            className={cn(
                                                "text-[10px] font-semibold uppercase tracking-widest border rounded-md px-2 py-1.5 bg-[var(--app-surface-1)] hover:bg-[var(--app-surface-2)] transition-colors border-[var(--app-border-subtle)]",
                                                focusRing
                                            )}
                                            type="button"
                                            onClick={handleConfirmSelected}
                                        >
                                            {t("workspace.confirm")}
                                        </button>
                                        <button
                                            className={cn(
                                                "text-[10px] font-semibold uppercase tracking-widest border rounded-md px-2 py-1.5 bg-[var(--app-surface-1)] hover:bg-[var(--app-surface-2)] transition-colors border-[var(--app-border-subtle)]",
                                                focusRing
                                            )}
                                            type="button"
                                            onClick={handleRevertSelected}
                                        >
                                            {t("workspace.revertDraft")}
                                        </button>
                                    </div>
                                    <div className="flex flex-wrap gap-1">
                                        {selectedCard.content.data.tags?.length ? (
                                            selectedCard.content.data.tags.slice(0, 6).map((tag) => (
                                                <Badge key={tag} variant="secondary" className="text-[9px] px-1.5 py-0">
                                                    {tag}
                                                </Badge>
                                            ))
                                        ) : (
                                            <span className="text-[10px] text-muted-foreground">{t("workspace.noTags")}</span>
                                        )}
                                    </div>
                                    <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                                        {selectedCard.edit_state.status === "confirmed" ? (
                                            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                                        ) : (
                                            <Clock className="w-3.5 h-3.5" />
                                        )}
                                        {selectedCard.edit_state.status}
                                    </div>
                                    <div className="text-[10px] text-muted-foreground">
                                        {t("workspace.updatedAt", { date: new Date(selectedCard.meta.modified_at).toLocaleString() })}
                                    </div>
                                </div>
                            ) : (
                                <div className="text-xs text-muted-foreground">
                                    {t("workspace.selectHint")}
                                </div>
                            )}
                        </div>
                        )}
                    </div>
                    <div className="border-t border-[var(--app-border-subtle)] bg-[var(--app-surface-2)]/80 backdrop-blur-sm">
                        <div className="max-w-[1280px] mx-auto px-6 py-3 flex flex-wrap items-center justify-between gap-3">
                            <div className="text-xs text-muted-foreground">
                                {t("workspace.selectedCount", { count: selectedCard ? 1 : 0 })}
                            </div>
                            <div className="flex items-center gap-2">
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    disabled={statusCounts.total === 0}
                                    onClick={handleApproveAll}
                                >
                                    {t("workspace.approveAll")}
                                </Button>
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    disabled={!selectedCard || !selectedTemplate}
                                    onClick={handleApplyQuestionType}
                                >
                                    {t("workspace.applyQuestionType")}
                                </Button>
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    disabled={statusCounts.confirmed === 0 || exporting}
                                    onClick={handleExportApkg}
                                    className="inline-flex items-center gap-1.5"
                                >
                                    <Download className="w-3 h-3" />
                                    {exporting || exportTask?.status === "processing" ? t("workspace.exportingApkg") : t("workspace.exportApkg")}
                                </Button>
                                {selectedCard && (
                                    <>
                                        <Button
                                            type="button"
                                            size="sm"
                                            onClick={handleConfirmSelected}
                                        >
                                            {t("workspace.confirm")}
                                        </Button>
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="secondary"
                                            onClick={handleRevertSelected}
                                        >
                                            {t("workspace.revertDraft")}
                                        </Button>
                                    </>
                                )}
                            </div>
                            {(exportTask || exportError) && (
                                <div className="text-[10px] text-muted-foreground break-all">
                                    {exportError
                                        ? exportError
                                        : exportTask?.status === "completed"
                                            ? `${t("workspace.exportReady")} ${exportTask.file_name || ""}`
                                            : exportTask?.status === "failed"
                                                ? `${t("workspace.exportFailed")} ${exportTask.error || ""}`
                                                : t("workspace.exportingApkg")}
                                    {exportTask?.status === "completed" && (
                                        <button
                                            type="button"
                                            className={cn("ml-1 underline underline-offset-2 text-[var(--app-accent-foreground)]", focusRing)}
                                            onClick={handleDownloadApkg}
                                        >
                                            {t("workspace.downloadApkg")}
                                        </button>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            ) : (
                <>
                    <div ref={containerRef} className="flex-1 overflow-y-auto p-4 custom-scrollbar">
                        {filteredCards.length === 0 && workspacePhase !== "loading" && (
                            <div className="flex flex-col items-center justify-center h-[200px] text-center text-muted-foreground bg-[var(--app-surface-2)]/60 border border-[var(--app-border-subtle)] rounded-lg w-full">
                                <div className="text-sm font-medium text-foreground/80">{t("workspace.filterEmptyTitle")}</div>
                                <div className="text-xs mt-1 max-w-[320px]">{t("workspace.filterEmptyDesc")}</div>
                            </div>
                        )}
                        {viewMode === "grid" ? (
                            <div className={cn(
                                "grid gap-4",
                                density === "compact" ? "sm:grid-cols-2" : "sm:grid-cols-1 lg:grid-cols-2"
                            )}>
                                {visibleCards.map((card) => renderCard(card))}
                            </div>
                        ) : (
                            <>
                                {virtualEnabled ? (
                                    <div style={{ height: totalHeight, position: "relative" }}>
                                        <div style={{ transform: `translateY(${offsetY}px)` }} className="space-y-4">
                                            {renderCards.map((card) => renderCard(card))}
                                        </div>
                                    </div>
                                ) : (
                                    <div className="space-y-4">
                                        {visibleCards.map((card) => renderCard(card))}
                                    </div>
                                )}
                            </>
                        )}
                        {filteredCards.length > visibleCards.length && (
                            <button
                                className={cn(
                                    "mt-4 w-full text-xs uppercase tracking-[0.2em] font-semibold border rounded-md py-2 bg-[var(--app-surface-1)] hover:bg-[var(--app-surface-2)] transition-colors border-[var(--app-border-subtle)]",
                                    focusRing
                                )}
                                type="button"
                                onClick={() => setSize(size + 1)}
                                disabled={isValidating}
                            >
                                {isValidating
                                    ? t("workspace.loading")
                                    : t("workspace.loadMore", { count: filteredCards.length - visibleCards.length })}
                            </button>
                        )}
                    </div>
                    <div className="border-t border-[var(--app-border-subtle)] bg-[var(--app-surface-2)] p-3 space-y-3">
                <div className="grid grid-cols-2 gap-2">
                    <button
                        className={cn(
                            "text-[10px] font-semibold uppercase tracking-widest border rounded-md px-2 py-1.5 bg-[var(--app-surface-1)] hover:bg-[var(--app-surface-2)] transition-colors border-[var(--app-border-subtle)]",
                            focusRing
                        )}
                        type="button"
                        disabled={statusCounts.total === 0}
                        onClick={handleApproveAll}
                    >
                        {t("workspace.approveAll")}
                    </button>
                    <button
                        className={cn(
                            "text-[10px] font-semibold uppercase tracking-widest border rounded-md px-2 py-1.5 bg-[var(--app-surface-1)] hover:bg-[var(--app-surface-2)] transition-colors border-[var(--app-border-subtle)]",
                            focusRing
                        )}
                        type="button"
                        disabled={!selectedCard || !selectedTemplate}
                        onClick={handleApplyQuestionType}
                    >
                        {t("workspace.applyQuestionType")}
                    </button>
                    <button
                        className={cn(
                            "text-[10px] font-semibold uppercase tracking-widest border rounded-md px-2 py-1.5 bg-[var(--app-surface-1)] hover:bg-[var(--app-surface-2)] transition-colors border-[var(--app-border-subtle)] inline-flex items-center justify-center gap-1.5",
                            focusRing
                        )}
                        type="button"
                        disabled={statusCounts.confirmed === 0 || exporting}
                        onClick={handleExportApkg}
                    >
                        <Download className="w-3 h-3" />
                        {exporting || exportTask?.status === "processing" ? t("workspace.exportingApkg") : t("workspace.exportApkg")}
                    </button>
                </div>
                {(exportTask || exportError) && (
                    <div className="text-[10px] text-muted-foreground break-all">
                        {exportError
                            ? exportError
                            : exportTask?.status === "completed"
                                ? `${t("workspace.exportReady")} ${exportTask.file_name || ""}`
                                : exportTask?.status === "failed"
                                    ? `${t("workspace.exportFailed")} ${exportTask.error || ""}`
                                    : t("workspace.exportingApkg")}
                        {exportTask?.status === "completed" && (
                            <button
                                type="button"
                                className={cn("ml-1 underline underline-offset-2 text-[var(--app-accent-foreground)]", focusRing)}
                                onClick={handleDownloadApkg}
                            >
                                {t("workspace.downloadApkg")}
                            </button>
                        )}
                    </div>
                )}
                {selectedCard ? (
                    <div className="space-y-2">
                        <div className="flex items-center justify-between">
                            <div className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">{t("workspace.inspector")}</div>
                            <Badge variant="outline" className="text-[9px] font-mono">
                                {selectedCard.suggested_question_type || selectedCard.content.model}
                            </Badge>
                        </div>
                        <div className="text-xs font-semibold flex items-center gap-2">
                            <FileText className="w-3.5 h-3.5 text-muted-foreground" />
                            {selectedCard.content.data.front.slice(0, 80)}
                        </div>
                        <div className="space-y-1">
                            <div className="text-[9px] uppercase tracking-[0.2em] text-muted-foreground">{t("workspace.questionTypeLabel")}</div>
                            <select
                                className={cn(
                                    "w-full text-xs rounded-md border bg-[var(--app-surface-1)] px-2 py-1.5 border-[var(--app-border-subtle)]",
                                    focusRing
                                )}
                                disabled={templateOptions.length === 0}
                                value={selectedTemplate}
                                onChange={(event) => setSelectedTemplate(event.target.value)}
                            >
                                {templateOptions.map((option) => (
                                    <option key={option.id} value={option.id}>
                                        {option.label}
                                    </option>
                                ))}
                            </select>
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                            <button
                                className={cn(
                                    "text-[10px] font-semibold uppercase tracking-widest border rounded-md px-2 py-1.5 bg-[var(--app-surface-1)] hover:bg-[var(--app-surface-2)] transition-colors border-[var(--app-border-subtle)]",
                                    focusRing
                                )}
                                type="button"
                                onClick={handleConfirmSelected}
                            >
                                {t("workspace.confirm")}
                            </button>
                            <button
                                className={cn(
                                    "text-[10px] font-semibold uppercase tracking-widest border rounded-md px-2 py-1.5 bg-[var(--app-surface-1)] hover:bg-[var(--app-surface-2)] transition-colors border-[var(--app-border-subtle)]",
                                    focusRing
                                )}
                                type="button"
                                onClick={handleRevertSelected}
                            >
                                {t("workspace.revertDraft")}
                            </button>
                        </div>
                        <div className="flex flex-wrap gap-1">
                            {selectedCard.content.data.tags?.length ? (
                                selectedCard.content.data.tags.slice(0, 6).map((tag) => (
                                    <Badge key={tag} variant="secondary" className="text-[9px] px-1.5 py-0">
                                        {tag}
                                    </Badge>
                                ))
                            ) : (
                                <span className="text-[10px] text-muted-foreground">{t("workspace.noTags")}</span>
                            )}
                        </div>
                        <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                            {selectedCard.edit_state.status === "confirmed" ? (
                                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                            ) : (
                                <Clock className="w-3.5 h-3.5" />
                            )}
                            {selectedCard.edit_state.status}
                        </div>
                        <div className="text-[10px] text-muted-foreground">
                            {t("workspace.updatedAt", { date: new Date(selectedCard.meta.modified_at).toLocaleString() })}
                        </div>
                    </div>
                ) : (
                    <div className="text-xs text-muted-foreground">
                        {t("workspace.selectHint")}
                    </div>
                )}
                    </div>
                </>
            )}
            <style jsx>{`
                .custom-scrollbar::-webkit-scrollbar {
                    width: 4px;
                }
                .custom-scrollbar::-webkit-scrollbar-track {
                    background: transparent;
                }
                .custom-scrollbar::-webkit-scrollbar-thumb {
                    background: rgba(0, 0, 0, 0.1);
                    border-radius: 10px;
                }
                .animate-spin-slow {
                    animation: spin 8s linear infinite;
                }
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
            `}</style>
        </div>
    );
}

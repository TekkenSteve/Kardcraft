"use client";

import Link from "next/link";
import Image from "next/image";
import dynamic from "next/dynamic";
import { usePathname, useSearchParams, useRouter } from "next/navigation";
import { Plus, History, Sparkles, Microscope, Bot, CalendarClock, MoreHorizontal, Pencil, Pin, Trash2, LayoutTemplate } from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";
import { useEffect, useState, Suspense, useCallback, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Session, updateSession, deleteSession, isUnauthenticatedApiError } from "@/lib/kardcraft/api";
import { listSessions } from "@/lib/kardcraft/session-repository";
import { dedupeSessionsById } from "@/lib/kardcraft/session-list";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarGroupContent,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { useRegistryViewModel } from "@/lib/run/system";
import { toSessionKey } from "@/lib/run/types";
import { useSessionSelector } from "@/lib/session/system";

const UserPanel = dynamic(
  () => import("@/components/user-panel").then((mod) => mod.UserPanel),
  { ssr: false },
);

function SidebarInner() {
  const pathname = usePathname();
  const safePathname = pathname ?? "";
  const searchParams = useSearchParams();
  const router = useRouter();
  const currentSessionId = searchParams?.get("session_id") ?? null;
  const [editingSession, setEditingSession] = useState<Session | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [hoveredSessionId, setHoveredSessionId] = useState<string | null>(null);
  const lastKnownSessionIdRef = useRef<string | null>(null);
  const prevStatusRef = useRef<string | null>(null);
  const { isMobile, setOpenMobile } = useSidebar();
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  
  const registry = useRegistryViewModel();
  const activeSummary = registry.sessions.find((session) => session.sessionKey === toSessionKey(currentSessionId && currentSessionId !== "new" ? currentSessionId : null));
  const runStatus = activeSummary?.status ?? "idle";
  const streamingTitle = activeSummary?.sessionTitle ?? null;
  const userId = useSessionSelector((snapshot) => snapshot.context.session?.identity?.id ?? null);

  // Close sidebar on mobile after navigation
  const handleNavClick = useCallback(() => {
    if (isMobile) {
      setOpenMobile(false);
    }
  }, [isMobile, setOpenMobile]);

  const navigateToFreshSession = useCallback((event?: React.MouseEvent) => {
    event?.preventDefault();
    handleNavClick();
    router.push(`/run-detail?session_id=new&new_session=${Date.now()}`);
  }, [handleNavClick, router]);

  const sessionsKey = useMemo(
    () => (userId ? (["recent-sessions", userId] as const) : null),
    [userId],
  );
  const sessionsFetcher = useCallback(async () => {
    try {
      const data = await listSessions(10, 0);
      return data.sessions || [];
    } catch (error) {
      if (isUnauthenticatedApiError(error)) {
        return [];
      }
      throw error;
    }
  }, []);

  const sessionsQuery = useQuery({
    queryKey: sessionsKey || ["recent-sessions", "anonymous"],
    queryFn: sessionsFetcher,
    enabled: !!sessionsKey,
    staleTime: 10_000,
    refetchOnWindowFocus: false,
  });

  const recentSessions = useMemo<Session[]>(
    () => dedupeSessionsById(sessionsQuery.data || []),
    [sessionsQuery.data],
  );

  const handleEditTitle = useCallback((session: Session) => {
    setEditingSession(session);
    setEditingTitle(session.title || "");
  }, [setEditingSession, setEditingTitle]);

  const handleSaveTitle = useCallback(async () => {
    if (!editingSession) return;
    const nextTitle = editingTitle.trim();
    await updateSession(editingSession.session_id, { title: nextTitle });
    queryClient.setQueryData<Session[] | undefined>(sessionsKey || ["recent-sessions", "anonymous"], (prev) =>
      (prev || []).map((s) =>
        s.session_id === editingSession.session_id ? { ...s, title: nextTitle } : s
      )
    );
    await queryClient.invalidateQueries({ queryKey: ["recent-sessions"] });
    setEditingSession(null);
  }, [editingSession, editingTitle, queryClient, sessionsKey, setEditingSession]);

  const handleTogglePin = useCallback(async (session: Session) => {
    const nextPinned = !session.pinned;
    await updateSession(session.session_id, { pinned: nextPinned });
    queryClient.setQueryData<Session[] | undefined>(sessionsKey || ["recent-sessions", "anonymous"], (prev) =>
      (prev || []).map((s) =>
        s.session_id === session.session_id ? { ...s, pinned: nextPinned } : s
      )
    );
    await queryClient.invalidateQueries({ queryKey: ["recent-sessions"] });
  }, [queryClient, sessionsKey]);

  const handleDeleteSession = useCallback(async (session: Session) => {
    const confirmed = window.confirm(t("sidebar.deleteConfirm"));
    if (!confirmed) return;
    await deleteSession(session.session_id);
    queryClient.setQueryData<Session[] | undefined>(sessionsKey || ["recent-sessions", "anonymous"], (prev) =>
      (prev || []).filter((s) => s.session_id !== session.session_id)
    );
    await queryClient.invalidateQueries({ queryKey: ["recent-sessions"] });
    if (currentSessionId === session.session_id) {
      router.push("/runs");
    }
  }, [currentSessionId, queryClient, router, sessionsKey, t]);

  const visibleSessions = useMemo(() => (userId ? recentSessions : []), [recentSessions, userId]);

  // Refresh when navigating to a new session (e.g., after creating a task)
  // This detects when currentSessionId changes to a value not in our list
  useEffect(() => {
    if (!currentSessionId || currentSessionId === "new") return;
    if (currentSessionId === lastKnownSessionIdRef.current) return;
    
    lastKnownSessionIdRef.current = currentSessionId;
    
    // Check if this session is already in our list
    const sessionExists = visibleSessions.some(s => s.session_id === currentSessionId);
    if (!sessionExists) {
      // New session detected, refresh the list after a short delay
      // (give the backend time to persist the session)
      const timer = setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: ["recent-sessions"] });
      }, 1000);
      return () => clearTimeout(timer);
    }
  }, [currentSessionId, queryClient, visibleSessions]);

  // Auto-refresh when a task completes (to update title)
  useEffect(() => {
    // Detect transition from running to completed
    if (prevStatusRef.current === "running" && runStatus === "completed") {
      // Delay refresh to allow backend to update session title
      const timer = setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: ["recent-sessions"] });
      }, 1500);
      return () => clearTimeout(timer);
    }
    prevStatusRef.current = runStatus;
  }, [queryClient, runStatus]);

  // Update sidebar immediately when streaming title arrives (title now generated at task start)
  // Re-run when recentSessions changes to handle case where title arrives before session is loaded
  useEffect(() => {
    if (!streamingTitle || !currentSessionId || currentSessionId === "new") return;

    // Check if current session exists and needs title update
    const session = visibleSessions.find(s => s.session_id === currentSessionId);
    if (session && !session.title) {
      queryClient.setQueryData<Session[] | undefined>(sessionsKey || ["recent-sessions", "anonymous"], (prev) =>
        (prev || []).map((item) =>
          item.session_id === currentSessionId
            ? { ...item, title: streamingTitle }
            : item
        )
      );
    }
  }, [currentSessionId, queryClient, sessionsKey, streamingTitle, visibleSessions]);

  const routes = [
    {
      label: t("sidebar.newTask"),
      icon: Plus,
      href: "/run-detail?session_id=new",
      active: safePathname.startsWith("/run-detail") && currentSessionId === "new",
    },
    {
      label: t("sidebar.myAgents"),
      icon: Bot,
      href: "/agents",
      active: safePathname.startsWith("/agents"),
    },
    {
      label: t("sidebar.schedules"),
      icon: CalendarClock,
      href: "/schedules",
      active: safePathname.startsWith("/schedules"),
    },
    {
      label: t("sidebar.cardTemplates"),
      icon: LayoutTemplate,
      href: "/templates",
      active: safePathname.startsWith("/templates"),
    },
  ];

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center justify-between w-full group-data-[collapsible=icon]:justify-center">
          <Link href="/run-detail?session_id=new" onClick={navigateToFreshSession} className="flex items-center gap-2 px-2 py-2 hover:opacity-90 transition-opacity group-data-[collapsible=icon]:hidden">
            <Image
              src="/app-icon.png"
              alt="Kardcraft Agents"
              width={28}
              height={28}
              className="rounded-md"
              onError={(e) => {
                // Hide image on error, text will show
                e.currentTarget.style.display = 'none';
              }}
            />
            <h2 className="text-[15px] font-semibold tracking-[0.02em]">
              Kardcraft
            </h2>
          </Link>
          <SidebarTrigger className="cursor-pointer" />
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarMenu>
          {routes.map((route) => (
            <SidebarMenuItem key={route.href}>
              <SidebarMenuButton
                asChild
                isActive={route.active}
                className="hover:bg-[var(--app-sidebar-hover-bg)] data-[active=true]:bg-[var(--app-sidebar-active-bg)] data-[active=true]:text-[var(--app-sidebar-active-text)] data-[active=true]:shadow-[inset_0_0_0_1px_var(--app-sidebar-active-border)] data-[active=true]:font-semibold"
              >
                <Link
                  href={route.href}
                  onClick={(e) => {
                    if (route.href === "/run-detail?session_id=new") {
                      navigateToFreshSession(e);
                      return;
                    }
                    if (route.active) {
                      e.preventDefault();
                      return;
                    }
                    handleNavClick();
                  }}
                >
                  <route.icon />
                  <span>{route.label}</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>

        {visibleSessions.length > 0 && (
          <SidebarGroup className="mt-4">
            <div className="flex items-center justify-between px-2">
              <SidebarGroupLabel className="text-xs text-muted-foreground p-0">
                {t("sidebar.recents")}
              </SidebarGroupLabel>
              <Link
                href="/runs"
                onClick={handleNavClick}
                className="h-5 w-5 flex items-center justify-center rounded-md hover:bg-muted transition-colors group-data-[collapsible=icon]:hidden"
                title={t("sidebar.viewAll")}
              >
                <History className="h-3 w-3 text-muted-foreground" />
              </Link>
            </div>
            <SidebarGroupContent>
              <SidebarMenu>
                {visibleSessions.map((session) => {
                  const isActive = currentSessionId === session.session_id;
                  const isResearch = session.is_research_session;
                  // Friendly display: prefer title, else truncated query, else "New task…"
                  const truncatedQuery = session.latest_task_query 
                    ? (session.latest_task_query.length > 30 
                        ? session.latest_task_query.slice(0, 30) + "…" 
                        : session.latest_task_query)
                    : null;
                  const displayTitle = session.title || truncatedQuery || t("sidebar.newTaskPlaceholder");
                  return (
                    <SidebarMenuItem
                      key={session.session_id}
                      className="group"
                      onMouseEnter={() => setHoveredSessionId(session.session_id)}
                      onMouseLeave={() => setHoveredSessionId((prev) => prev === session.session_id ? null : prev)}
                    >
                      <div className="flex items-center gap-1">
                        <SidebarMenuButton
                          asChild
                          isActive={isActive}
                          className="h-auto py-1.5 flex-1 hover:bg-[var(--app-sidebar-hover-bg)] data-[active=true]:bg-[var(--app-sidebar-active-bg)] data-[active=true]:text-[var(--app-sidebar-active-text)] data-[active=true]:shadow-[inset_0_0_0_1px_var(--app-sidebar-active-border)] data-[active=true]:font-semibold"
                    >
                      <Link
                        href={`/run-detail?session_id=${session.session_id}`}
                        onClick={(e) => {
                          if (isActive) {
                                e.preventDefault();
                                return;
                              }
                              handleNavClick();
                            }}
                          >
                            {isResearch ? (
                              <Microscope className="h-3.5 w-3.5 text-violet-500 shrink-0" />
                            ) : (
                              <Sparkles className="h-3.5 w-3.5 text-amber-500 shrink-0" />
                            )}
                              <span className={`truncate text-sm ${!session.title ? 'text-muted-foreground' : ''}`}>
                              {displayTitle}
                            </span>
                          </Link>
                        </SidebarMenuButton>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className={`h-7 w-7 transition-opacity ${hoveredSessionId === session.session_id ? "opacity-100" : "opacity-0"}`}
                              aria-label={t("sidebar.editTitle")}
                              onClick={(e) => e.preventDefault()}
                            >
                              <MoreHorizontal className="h-4 w-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-40">
                            <DropdownMenuItem onClick={() => handleEditTitle(session)}>
                              <Pencil className="h-4 w-4" />
                              {t("sidebar.editTitle")}
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => handleTogglePin(session)}>
                              <Pin className="h-4 w-4" />
                              {session.pinned ? t("common.unpin") : t("common.pin")}
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem onClick={() => handleDeleteSession(session)} className="text-red-600">
                              <Trash2 className="h-4 w-4" />
                              {t("common.delete")}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        )}
      </SidebarContent>
      <SidebarFooter>
        <div className="flex items-center justify-between px-2 py-2 group-data-[collapsible=icon]:justify-center">
          <span className="text-sm group-data-[collapsible=icon]:hidden">{t("sidebar.theme")}</span>
          <ThemeToggle />
        </div>
        <div className="flex items-center justify-center px-2 py-2">
          <UserPanel />
        </div>
      </SidebarFooter>
      <Dialog open={!!editingSession} onOpenChange={(open) => !open && setEditingSession(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("sidebar.editTitleDialog")}</DialogTitle>
            <DialogDescription>{t("sidebar.editTitlePlaceholder")}</DialogDescription>
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
    </Sidebar>
  );
}

export function AppSidebar() {
  return (
    <Suspense fallback={<Sidebar><SidebarContent /></Sidebar>}>
      <SidebarInner />
    </Suspense>
  );
}

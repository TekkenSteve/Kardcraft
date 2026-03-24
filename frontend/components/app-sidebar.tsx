"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname, useSearchParams, useRouter } from "next/navigation";
import { Plus, History, Sparkles, Microscope, Bot, CalendarClock, MoreHorizontal, Pencil, Pin, Trash2, LayoutTemplate } from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";
import { UserPanel } from "@/components/user-panel";
import { useEffect, useState, Suspense, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useSelector } from "react-redux";
import { RootState } from "@/lib/store";
import { Session, updateSession, deleteSession } from "@/lib/kardcraft/api";
import { listSessions } from "@/lib/kardcraft/session-repository";
import useSWR from "swr";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
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

function SidebarInner() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const currentSessionId = searchParams.get("session_id");
  const [recentSessions, setRecentSessions] = useState<Session[]>([]);
  const [editingSession, setEditingSession] = useState<Session | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [hoveredSessionId, setHoveredSessionId] = useState<string | null>(null);
  const lastKnownSessionIdRef = useRef<string | null>(null);
  const prevStatusRef = useRef<string | null>(null);
  const { isMobile, setOpenMobile } = useSidebar();
  const { t } = useTranslation();
  
  // Subscribe to run status for auto-refresh on task completion
  const runStatus = useSelector((state: RootState) => state.run.status);
  // Subscribe to session title from streaming events (title now generated at start of task)
  const streamingTitle = useSelector((state: RootState) => state.run.sessionTitle);
  const userId = useSelector((state: RootState) => state.auth.userId);

  // Close sidebar on mobile after navigation
  const handleNavClick = useCallback(() => {
    if (isMobile) {
      setOpenMobile(false);
    }
  }, [isMobile, setOpenMobile]);

  const sessionsKey = userId ? ["recent-sessions", userId] : null;
  const sessionsFetcher = useCallback(async () => {
    try {
      const data = await listSessions(10, 0);
      return data.sessions || [];
    } catch (error) {
      // Silently fail if unauthorized (user not logged in) or network error
      if (error instanceof Error &&
        (error.message.includes("unauthorized") ||
          error.message.includes("Unauthorized") ||
          error.message.includes("Failed to fetch"))) {
        return [];
      }
      throw error;
    }
  }, []);

  const { data: swrSessions, mutate: mutateSessions } = useSWR<Session[]>(
    sessionsKey,
    sessionsFetcher,
    {
      dedupingInterval: 10_000,
      revalidateOnFocus: true,
      keepPreviousData: true,
    }
  );

  useEffect(() => {
    if (swrSessions) {
      setRecentSessions(swrSessions);
    }
  }, [swrSessions]);

  const handleEditTitle = useCallback((session: Session) => {
    setEditingSession(session);
    setEditingTitle(session.title || "");
  }, []);

  const handleSaveTitle = useCallback(async () => {
    if (!editingSession) return;
    const nextTitle = editingTitle.trim();
    await updateSession(editingSession.session_id, { title: nextTitle });
    setRecentSessions((prev) =>
      prev.map((s) =>
        s.session_id === editingSession.session_id ? { ...s, title: nextTitle } : s
      )
    );
    setEditingSession(null);
  }, [editingSession, editingTitle]);

  const handleTogglePin = useCallback(async (session: Session) => {
    const nextPinned = !session.pinned;
    await updateSession(session.session_id, { pinned: nextPinned });
    setRecentSessions((prev) =>
      prev.map((s) =>
        s.session_id === session.session_id ? { ...s, pinned: nextPinned } : s
      )
    );
    mutateSessions();
  }, [mutateSessions]);

  const handleDeleteSession = useCallback(async (session: Session) => {
    const confirmed = window.confirm(t("sidebar.deleteConfirm"));
    if (!confirmed) return;
    await deleteSession(session.session_id);
    setRecentSessions((prev) => prev.filter((s) => s.session_id !== session.session_id));
    mutateSessions();
    if (currentSessionId === session.session_id) {
      router.push("/runs");
    }
  }, [currentSessionId, mutateSessions, router, t]);

  const visibleSessions = userId ? recentSessions : [];

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
      const timer = setTimeout(() => mutateSessions(), 1000);
      return () => clearTimeout(timer);
    }
  }, [currentSessionId, visibleSessions, mutateSessions]);

  // Auto-refresh when a task completes (to update title)
  useEffect(() => {
    // Detect transition from running to completed
    if (prevStatusRef.current === "running" && runStatus === "completed") {
      // Delay refresh to allow backend to update session title
      const timer = setTimeout(() => mutateSessions(), 1500);
      return () => clearTimeout(timer);
    }
    prevStatusRef.current = runStatus;
  }, [runStatus, mutateSessions]);

  // Update sidebar immediately when streaming title arrives (title now generated at task start)
  // Re-run when recentSessions changes to handle case where title arrives before session is loaded
  useEffect(() => {
    if (!streamingTitle || !currentSessionId || currentSessionId === "new") return;

    // Check if current session exists and needs title update
    const session = visibleSessions.find(s => s.session_id === currentSessionId);
    if (session && !session.title) {
      // Update the title in local state for immediate UI feedback
      setRecentSessions(prev => prev.map(s =>
        s.session_id === currentSessionId
          ? { ...s, title: streamingTitle }
          : s
      ));
    }
  }, [streamingTitle, currentSessionId, visibleSessions]);

  const routes = [
    {
      label: t("sidebar.newTask"),
      icon: Plus,
      href: "/run-detail?session_id=new",
      active: pathname.startsWith("/run-detail") && currentSessionId === "new",
    },
    {
      label: t("sidebar.myAgents"),
      icon: Bot,
      href: "/agents",
      active: pathname.startsWith("/agents"),
    },
    {
      label: t("sidebar.schedules"),
      icon: CalendarClock,
      href: "/schedules",
      active: pathname.startsWith("/schedules"),
    },
    {
      label: t("sidebar.cardTemplates"),
      icon: LayoutTemplate,
      href: "/templates",
      active: pathname.startsWith("/templates"),
    },
  ];

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center justify-between w-full group-data-[collapsible=icon]:justify-center">
          <Link href="/run-detail?session_id=new" onClick={handleNavClick} className="flex items-center gap-2 px-2 py-2 hover:opacity-90 transition-opacity group-data-[collapsible=icon]:hidden">
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

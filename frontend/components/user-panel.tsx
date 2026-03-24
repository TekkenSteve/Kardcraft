"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { User, LogOut, Settings, Globe, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Separator } from "@/components/ui/separator";
import { LoginDialog } from "@/components/auth/login-dialog";
import { RegisterDialog } from "@/components/auth/register-dialog";
import { ory, type Session } from "@/lib/kratos/client";
import { cn } from "@/lib/utils";
import { useDispatch } from "react-redux";
import { setProfile, clearCredentials } from "@/lib/features/authSlice";

export function UserPanel() {
  const { t, i18n } = useTranslation();
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [loginOpen, setLoginOpen] = useState(false);
  const [registerOpen, setRegisterOpen] = useState(false);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const dispatch = useDispatch();

  useEffect(() => {
    checkSession();

    // Listen for auth state changes
    const handleAuthChange = () => {
      checkSession();
    };

    window.addEventListener('auth-state-changed', handleAuthChange);

    return () => {
      window.removeEventListener('auth-state-changed', handleAuthChange);
    };
  }, []);

  const checkSession = async () => {
    try {
      const { data } = await ory.toSession();
      setSession(data);
      const traits = data?.identity?.traits;
      let displayName = "";
      if (traits?.name && typeof traits.name === 'object') {
        const nameObj = traits.name as { first?: string; last?: string };
        displayName = `${nameObj.first || ""} ${nameObj.last || ""}`.trim();
      } else if (typeof traits?.name === 'string') {
        displayName = traits.name;
      }
      if (!displayName && traits?.email) {
        displayName = traits.email;
      }
      dispatch(setProfile({
        userId: data?.identity?.id ?? null,
        name: displayName || null,
        expiresAt: data?.expires_at,
      }));
    } catch (error) {
      setSession(null);
      dispatch(clearCredentials());
    } finally {
      setLoading(false);
    }
  };

  const handleLoginSuccess = () => {
    checkSession();
  };

  const handleLogout = async () => {
    try {
      const { data } = await ory.createBrowserLogoutFlow();
      await ory.updateLogoutFlow({
        token: data.logout_token,
      });
      setSession(null);
      dispatch(clearCredentials());
      setPopoverOpen(false);

      // Trigger a custom event to notify other components
      window.dispatchEvent(new CustomEvent('auth-state-changed'));
    } catch (error) {
      console.error("Logout failed:", error);
    }
  };

  const changeLanguage = (lng: string) => {
    i18n.changeLanguage(lng);
    if (typeof window !== "undefined") {
      window.localStorage.setItem("kc_language", lng);
    }
  };

  const getUserInitials = () => {
    if (!session?.identity) return "?";
    const traits = session.identity.traits;
    let name = "";

    // Handle name object structure from Kratos
    if (traits.name && typeof traits.name === 'object') {
      const nameObj = traits.name as any;
      name = `${nameObj.first || ""} ${nameObj.last || ""}`.trim();
    } else if (typeof traits.name === 'string') {
      name = traits.name;
    }

    // Fallback to email if no name
    if (!name) {
      name = traits.email;
    }

    return name
      .split(" ")
      .map((n) => n[0])
      .join("")
      .toUpperCase()
      .slice(0, 2);
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg">
        <Avatar className="h-8 w-8">
          <AvatarFallback className="bg-muted">
            <User className="h-4 w-4" />
          </AvatarFallback>
        </Avatar>
      </div>
    );
  }

  // Not logged in - show login button
  if (!session) {
    return (
      <>
        <Button
          variant="ghost"
          className="w-full justify-start gap-2 px-2 py-1.5 h-auto hover:bg-accent group-data-[collapsible=icon]:justify-center"
          onClick={() => setLoginOpen(true)}
        >
          <Avatar className="h-8 w-8">
            <AvatarFallback className="bg-muted">
              <User className="h-4 w-4" />
            </AvatarFallback>
          </Avatar>
          <span className="text-sm font-medium group-data-[collapsible=icon]:hidden">{t("auth.login")}</span>
        </Button>

        <LoginDialog
          open={loginOpen}
          onOpenChange={setLoginOpen}
          onSuccess={handleLoginSuccess}
          onSwitchToRegister={() => {
            setLoginOpen(false);
            setRegisterOpen(true);
          }}
        />

        <RegisterDialog
          open={registerOpen}
          onOpenChange={setRegisterOpen}
          onSuccess={handleLoginSuccess}
          onSwitchToLogin={() => {
            setRegisterOpen(false);
            setLoginOpen(true);
          }}
        />
      </>
    );
  }

  // Logged in - show popover menu
  return (
    <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-between gap-2 px-2 py-1.5 h-auto hover:bg-accent group-data-[collapsible=icon]:justify-center"
        >
          <div className="flex items-center gap-2 min-w-0 group-data-[collapsible=icon]:min-w-fit">
            <Avatar className="h-8 w-8 shrink-0">
              <AvatarFallback className="bg-primary text-primary-foreground text-xs">
                {getUserInitials()}
              </AvatarFallback>
            </Avatar>
            <div className="flex flex-col items-start min-w-0 group-data-[collapsible=icon]:hidden">
              <span className="text-sm font-medium truncate max-w-[120px]">
                {(() => {
                  const traits = session?.identity?.traits;
                  if (!traits) return "User";
                  if (traits.name && typeof traits.name === 'object') {
                    const nameObj = traits.name as any;
                    return `${nameObj.first || ""} ${nameObj.last || ""}`.trim() || "User";
                  } else if (typeof traits.name === 'string') {
                    return traits.name || "User";
                  }
                  return "User";
                })()}
              </span>
              <span className="text-xs text-muted-foreground truncate max-w-[120px]">
                {session?.identity?.traits?.email}
              </span>
            </div>
          </div>
          <ChevronDown className="h-4 w-4 shrink-0 group-data-[collapsible=icon]:hidden" />
        </Button>
      </PopoverTrigger>

      <PopoverContent className="w-56 p-2" align="start" side="top">
        <div className="space-y-1">
          {/* Language Submenu */}
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="w-full justify-start gap-2 h-8 px-2"
              >
                <Globe className="h-4 w-4" />
                <span className="text-sm">{t("settings.language")}</span>
                <ChevronDown className="h-3 w-3 ml-auto" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-32 p-1" align="start" side="right">
              <div className="space-y-1">
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full justify-start h-7 px-2 text-xs"
                  onClick={() => {
                    changeLanguage("en");
                    setPopoverOpen(false);
                  }}
                >
                  {t("settings.english")}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full justify-start h-7 px-2 text-xs"
                  onClick={() => {
                    changeLanguage("zh");
                    setPopoverOpen(false);
                  }}
                >
                  {t("settings.chinese")}
                </Button>
              </div>
            </PopoverContent>
          </Popover>

          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start gap-2 h-8 px-2"
            disabled
          >
            <Settings className="h-4 w-4" />
            <span className="text-sm">{t("settings.title")}</span>
          </Button>

          <Separator className="my-1" />

          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start gap-2 h-8 px-2 text-destructive hover:text-destructive hover:bg-destructive/10"
            onClick={handleLogout}
          >
            <LogOut className="h-4 w-4" />
            <span className="text-sm">{t("auth.logout")}</span>
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

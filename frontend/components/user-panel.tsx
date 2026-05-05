"use client";

import { useEffect, useState } from "react";
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
import { useSessionCommands, useSessionSelector } from "@/lib/session/system";
import { getDisplayInitials, getSessionDisplayName, getSessionEmail } from "@/lib/session/profile";
import { LANGUAGE_COOKIE_KEY, type SupportedLanguage } from "@/lib/i18n/config";

export function UserPanel() {
    const { t, i18n } = useTranslation();
    const [loginOpen, setLoginOpen] = useState(false);
    const [registerOpen, setRegisterOpen] = useState(false);
    const [popoverOpen, setPopoverOpen] = useState(false);
    const [isHydrated, setIsHydrated] = useState(false);

    useEffect(() => {
        setIsHydrated(true);
    }, []);

    const session = useSessionSelector((snapshot) => snapshot.context.session);
    const isChecking = useSessionSelector(
        (snapshot) =>
            snapshot.matches("checking") ||
            snapshot.matches("refreshing"),
    );
    const { check, logout } = useSessionCommands();

    const displayName = getSessionDisplayName(session) ?? "User";
    const email = getSessionEmail(session);
    const initials = getDisplayInitials(displayName);

    const handleLogout = () => {
        logout();
        setPopoverOpen(false);
    };

    const changeLanguage = (lng: SupportedLanguage) => {
        i18n.changeLanguage(lng);
        document.cookie = `${LANGUAGE_COOKIE_KEY}=${lng}; path=/; max-age=31536000; samesite=lax`;
    };

    if (!isHydrated || (isChecking && !session)) {
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
                    onSuccess={() => {
                        check();
                    }}
                    onSwitchToRegister={() => {
                        setLoginOpen(false);
                        setRegisterOpen(true);
                    }}
                />

                <RegisterDialog
                    open={registerOpen}
                    onOpenChange={setRegisterOpen}
                    onSuccess={() => {
                        check();
                    }}
                    onSwitchToLogin={() => {
                        setRegisterOpen(false);
                        setLoginOpen(true);
                    }}
                />
            </>
        );
    }

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
                                {initials}
                            </AvatarFallback>
                        </Avatar>
                        <div className="flex flex-col items-start min-w-0 group-data-[collapsible=icon]:hidden">
                            <span className="text-sm font-medium truncate max-w-[120px]">
                                {displayName}
                            </span>
                            <span className="text-xs text-muted-foreground truncate max-w-[120px]">
                                {email}
                            </span>
                        </div>
                    </div>
                    <ChevronDown className="h-4 w-4 shrink-0 group-data-[collapsible=icon]:hidden" />
                </Button>
            </PopoverTrigger>

            <PopoverContent className="w-56 p-2" align="start" side="top">
                <div className="space-y-1">
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

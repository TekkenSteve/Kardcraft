"use client";

import { AppSidebar } from "@/components/app-sidebar";
import { SidebarProvider } from "@/components/ui/sidebar";

export function AppLayout({ children }: { children: React.ReactNode }) {
    return (
        <SidebarProvider>
            <div className="flex h-screen w-full overflow-hidden bg-background">
                <AppSidebar />
                <main className="flex-1 flex flex-col overflow-y-auto">
                    <div className="flex-1 min-h-0 overflow-hidden">
                        {children}
                    </div>
                </main>
            </div>
        </SidebarProvider>
    );
}

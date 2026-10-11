"use client";

import { useState } from "react";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { TopBar } from "@/components/layout/top-bar";
import { Sheet, SheetClose, SheetHeader } from "@/components/ui/sheet";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex min-h-screen bg-background">
      <aside className="hidden w-[236px] shrink-0 flex-col border-r border-sidebar-border bg-sidebar md:flex">
        <div className="flex h-12 items-center gap-2.5 border-b border-sidebar-border px-4">
          <div className="flex h-6 w-6 items-center justify-center rounded-[5px] bg-primary text-[11px] font-semibold text-primary-foreground">
            F
          </div>
          <div className="min-w-0 leading-tight">
            <p className="truncate text-[13px] font-semibold tracking-tight text-foreground">Focus</p>
            <p className="truncate text-[10px] font-medium text-muted-foreground">Analytics</p>
          </div>
        </div>
        <SidebarNav />
      </aside>

      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <div className="flex h-full flex-col bg-sidebar">
          <SheetHeader>
            <div className="flex items-center gap-2">
              <div className="flex h-6 w-6 items-center justify-center rounded-[5px] bg-primary text-[11px] font-semibold text-primary-foreground">
                F
              </div>
              <p className="text-[13px] font-semibold">Focus</p>
            </div>
            <SheetClose onClick={() => setMobileOpen(false)} />
          </SheetHeader>
          <SidebarNav onNavigate={() => setMobileOpen(false)} />
        </div>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onMenuClick={() => setMobileOpen(true)} />
        <main className="flex-1 px-4 py-5 md:px-7 md:py-7 lg:px-8">{children}</main>
      </div>
    </div>
  );
}

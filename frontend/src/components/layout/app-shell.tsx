"use client";

import { useState } from "react";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { TopBar } from "@/components/layout/top-bar";
import { Sheet, SheetClose, SheetHeader } from "@/components/ui/sheet";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex min-h-screen bg-background">
      <aside className="hidden w-64 shrink-0 border-r border-border bg-card/30 md:flex md:flex-col">
        <div className="border-b border-border p-6">
          <p className="font-serif text-xl font-semibold">Focus</p>
          <p className="text-xs text-muted-foreground">Sales intelligence</p>
        </div>
        <SidebarNav />
      </aside>

      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <div className="flex h-full flex-col">
          <SheetHeader>
            <div>
              <p className="font-serif text-lg font-semibold">Focus</p>
              <p className="text-xs text-muted-foreground">Меню</p>
            </div>
            <SheetClose onClick={() => setMobileOpen(false)} />
          </SheetHeader>
          <SidebarNav onNavigate={() => setMobileOpen(false)} />
        </div>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onMenuClick={() => setMobileOpen(true)} />
        <main className="flex-1 px-4 py-6 md:px-8 md:py-8">{children}</main>
      </div>
    </div>
  );
}

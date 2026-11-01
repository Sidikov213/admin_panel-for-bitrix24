"use client";

import { useState } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { TopBar } from "@/components/layout/top-bar";
import { Sheet, SheetClose, SheetHeader } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <div className={cn("flex items-center gap-2.5", compact && "justify-center")}>
      <div className="flex h-8 w-8 items-center justify-center rounded-[10px] bg-[#134e4a] text-[13px] font-semibold text-[#ecfdf8] shadow-[inset_0_0_0_1px_rgba(94,234,212,0.35)]">
        F
      </div>
      {compact ? null : (
        <div className="min-w-0 leading-tight">
          <p className="truncate text-[14px] font-semibold tracking-tight text-white">Focus Analytics</p>
          <p className="truncate text-[11px] text-[var(--sidebar-muted)]">Продажи</p>
        </div>
      )}
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  function toggleCollapsed() {
    setCollapsed((prev) => !prev);
  }

  return (
    <div className="app-shell h-dvh overflow-hidden bg-background" data-sidebar={collapsed ? "collapsed" : "expanded"}>
      <aside className="sidebar-shell fixed top-0 left-0 z-30 hidden h-dvh w-[var(--shell-sidebar-width)] flex-col border-r border-[var(--sidebar-border)] transition-[width] duration-200 ease-out md:flex">
        <div className={cn("flex h-[68px] shrink-0 items-center border-b border-[var(--sidebar-border)] px-4", collapsed && "justify-center px-2")}>
          <BrandMark compact={collapsed} />
        </div>
        <SidebarNav collapsed={collapsed} />
        <div className="shrink-0 border-t border-[var(--sidebar-border)] p-3">
          <button
            type="button"
            onClick={toggleCollapsed}
            className="flex w-full items-center justify-center gap-2 rounded-[12px] px-2 py-2 text-[12px] text-[#c5ced8] transition-colors hover:bg-[var(--sidebar-hover)] hover:text-white"
            aria-label={collapsed ? "Развернуть меню" : "Свернуть меню"}
          >
            {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
            {collapsed ? null : <span>Свернуть</span>}
          </button>
        </div>
      </aside>

      <Sheet open={mobileOpen} onOpenChange={setMobileOpen} className="sidebar-shell border-[var(--sidebar-border)]">
        <div className="flex h-full flex-col">
          <SheetHeader className="border-[var(--sidebar-border)] text-white">
            <BrandMark />
            <SheetClose onClick={() => setMobileOpen(false)} />
          </SheetHeader>
          <SidebarNav onNavigate={() => setMobileOpen(false)} />
        </div>
      </Sheet>

      <div className="ml-[var(--shell-sidebar-width)] flex h-dvh min-w-0 flex-col overflow-x-hidden overflow-y-auto transition-[margin-left] duration-200 ease-out">
        <TopBar onMenuClick={() => setMobileOpen(true)} />
        <main className="flex-1 px-4 py-5 md:px-7 md:py-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}

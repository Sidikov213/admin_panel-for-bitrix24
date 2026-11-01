"use client";

import { LogOut, Menu } from "lucide-react";
import { usePathname } from "next/navigation";
import { resolvePageSubtitle, resolvePageTitle } from "@/components/layout/nav-config";
import { useAuth } from "@/components/providers/auth-provider";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

function initials(email?: string | null) {
  if (!email) return "?";
  const local = email.split("@")[0] || email;
  return local.slice(0, 2).toUpperCase();
}

export function TopBar({ onMenuClick }: { onMenuClick: () => void }) {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const title = resolvePageTitle(pathname);
  const subtitle = resolvePageSubtitle(pathname);

  return (
    <header className="sticky top-0 z-20 flex items-center gap-4 border-b border-border/80 bg-background px-4 py-4 md:px-7 lg:px-8">
      <Button variant="ghost" size="icon" className="h-10 w-10 md:hidden" onClick={onMenuClick} aria-label="Меню">
        <Menu className="h-4 w-4" />
      </Button>

      <div className="min-w-0 flex-1">
        <h1 className="page-title truncate">{title}</h1>
        {subtitle ? <p className="mt-0.5 truncate text-[13px] text-muted-foreground">{subtitle}</p> : null}
      </div>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className="flex h-10 w-10 items-center justify-center rounded-full border border-border bg-card text-[12px] font-semibold text-foreground shadow-[var(--shadow-surface)] transition-colors hover:bg-muted"
            aria-label="Профиль"
          >
            {initials(user?.email)}
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          <DropdownMenuLabel className="font-normal">
            <div className="truncate text-sm font-medium">{user?.email ?? "—"}</div>
            <div className="text-xs capitalize text-muted-foreground">{user?.role ?? "—"}</div>
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            className="text-destructive focus:text-destructive"
            onClick={() => {
              void logout();
            }}
          >
            <LogOut className="mr-2 h-4 w-4" />
            Выйти
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  );
}

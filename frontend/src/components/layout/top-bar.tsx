"use client";

import { LogOut, Menu } from "lucide-react";
import { usePathname } from "next/navigation";
import { resolvePageTitle } from "@/components/layout/nav-config";
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

  return (
    <header className="sticky top-0 z-40 flex h-12 items-center gap-3 border-b border-border bg-background/90 px-4 md:px-6 backdrop-blur-[2px]">
      <Button variant="ghost" size="icon" className="h-8 w-8 md:hidden" onClick={onMenuClick} aria-label="Меню">
        <Menu className="h-4 w-4" />
      </Button>

      <div className="min-w-0 flex-1">
        <h1 className="truncate text-[15px] font-semibold tracking-tight text-foreground">{title}</h1>
      </div>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className="flex h-8 w-8 items-center justify-center rounded-full border border-border bg-card text-[11px] font-semibold text-foreground/80 transition-colors hover:bg-muted"
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

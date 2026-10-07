"use client";

import { LogOut, Menu, User } from "lucide-react";
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

export function TopBar({ onMenuClick }: { onMenuClick: () => void }) {
  const { user, logout } = useAuth();

  return (
    <header className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b border-border bg-background/90 px-4 backdrop-blur md:px-6">
      <Button variant="ghost" size="icon" className="md:hidden" onClick={onMenuClick} aria-label="Открыть меню">
        <Menu className="h-5 w-5" />
      </Button>
      <div className="flex flex-1 items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="truncate font-serif text-base font-semibold tracking-tight">Focus Analytics</p>
          <p className="hidden text-xs text-muted-foreground sm:block">Корпоративная аналитика продаж</p>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="gap-2">
              <User className="h-4 w-4" />
              <span className="hidden max-w-[12rem] truncate sm:inline">{user?.email ?? "…"}</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>
              <div className="text-xs text-muted-foreground">Роль</div>
              <div className="font-normal capitalize">{user?.role ?? "—"}</div>
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
      </div>
    </header>
  );
}

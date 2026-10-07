"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { mainNav, placeholderNav } from "@/components/layout/nav-config";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <nav className="flex flex-1 flex-col gap-6 p-4">
      <div>
        <p className="mb-2 px-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">Аналитика</p>
        <ul className="space-y-1">
          {mainNav.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            const Icon = item.icon;
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  onClick={onNavigate}
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                    active ? "bg-primary/10 text-primary font-medium" : "text-foreground/80 hover:bg-muted",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span>{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </div>
      <div>
        <p className="mb-2 px-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">Скоро</p>
        <ul className="space-y-1">
          {placeholderNav.map((item) => {
            const Icon = item.icon;
            return (
              <li key={item.label}>
                <span
                  className="flex cursor-not-allowed items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground opacity-70"
                  title={item.badge}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className="flex-1">{item.label}</span>
                  {item.badge ? (
                    <Badge variant="secondary" className="text-[10px]">
                      {item.badge}
                    </Badge>
                  ) : null}
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </nav>
  );
}

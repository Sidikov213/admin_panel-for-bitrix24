"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { futureNav, navGroups } from "@/components/layout/nav-config";
import { cn } from "@/lib/utils";

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <nav className="flex flex-1 flex-col gap-6 overflow-y-auto px-2.5 py-4">
      {navGroups.map((group) => (
        <div key={group.title}>
          <p className="mb-2 px-2.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-[#8a8983]">
            {group.title}
          </p>
          <ul className="space-y-0.5">
            {group.items.map((item) => {
              const active =
                pathname === item.href ||
                (item.href !== "/dashboard" && pathname.startsWith(`${item.href}/`)) ||
                (item.href === "/dashboard" && pathname === "/dashboard");
              const Icon = item.icon;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    className={cn(
                      "relative flex items-center gap-2.5 rounded-md py-1.5 pl-2.5 pr-2.5 text-[13px] transition-colors duration-150",
                      active
                        ? "bg-[var(--accent)] font-semibold text-[var(--accent-foreground)]"
                        : "text-[#4a4a46] hover:bg-[var(--sidebar-hover)] hover:text-foreground",
                    )}
                  >
                    {active ? (
                      <span
                        aria-hidden
                        className="absolute left-0 top-1.5 bottom-1.5 w-[2.5px] rounded-full bg-primary"
                      />
                    ) : null}
                    <Icon
                      className={cn(
                        "h-3.5 w-3.5 shrink-0",
                        active ? "text-primary opacity-100" : "opacity-70",
                      )}
                      strokeWidth={active ? 2 : 1.75}
                    />
                    <span className="truncate">{item.label}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}

      <div className="mt-auto border-t border-sidebar-border pt-3">
        <p className="mb-2 px-2.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-[#9a9993]">
          Скоро
        </p>
        <ul className="space-y-0.5">
          {futureNav.map((item) => {
            const Icon = item.icon;
            return (
              <li key={item.label}>
                <span className="flex cursor-not-allowed items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] text-[#9a9993]">
                  <Icon className="h-3.5 w-3.5 shrink-0 opacity-60" strokeWidth={1.75} />
                  <span className="flex-1 truncate">{item.label}</span>
                  <span className="text-[10px] text-[#b0afa8]">{item.badge}</span>
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </nav>
  );
}

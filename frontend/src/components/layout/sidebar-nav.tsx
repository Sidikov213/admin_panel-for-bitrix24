"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { adminNavGroup, futureNav, navGroups } from "@/components/layout/nav-config";
import { useAuth } from "@/components/providers/auth-provider";
import { cn } from "@/lib/utils";

function isActive(pathname: string, href: string) {
  if (href === "/dashboard") return pathname === "/dashboard";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function SidebarNav({
  onNavigate,
  collapsed = false,
}: {
  onNavigate?: () => void;
  collapsed?: boolean;
}) {
  const pathname = usePathname();
  const { user } = useAuth();
  const groups = user?.role === "admin" ? [...navGroups, adminNavGroup] : navGroups;

  return (
    <nav className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-3 py-4">
      {groups.map((group) => (
        <div key={group.title}>
          {collapsed ? null : (
            <p className="mb-1.5 px-2.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--sidebar-muted)]">
              {group.title}
            </p>
          )}
          <ul className="space-y-0.5">
            {group.items.map((item) => {
              const active = isActive(pathname, item.href);
              const Icon = item.icon;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    title={item.label}
                    onClick={onNavigate}
                    className={cn(
                      "flex items-center gap-2.5 rounded-[12px] px-2.5 py-2 text-[13.5px] transition-colors duration-150",
                      collapsed && "justify-center px-0",
                      active
                        ? "bg-[var(--sidebar-active)] font-semibold text-white shadow-[inset_0_0_0_1px_rgba(45,212,191,0.35)]"
                        : "text-[#c5ced8] hover:bg-[var(--sidebar-hover)] hover:text-white",
                    )}
                  >
                    <Icon
                      className={cn("h-4 w-4 shrink-0", active ? "text-[#5eead4]" : "text-[#9aa8b8]")}
                      strokeWidth={1.75}
                    />
                    {collapsed ? null : <span className="truncate">{item.label}</span>}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}

      <div>
        {collapsed ? null : (
          <p className="mb-1.5 px-2.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--sidebar-muted)]">
            Скоро
          </p>
        )}
        <ul className="space-y-0.5">
          {futureNav.map((item) => {
            const Icon = item.icon;
            return (
              <li key={item.label}>
                <span
                  title={item.label}
                  className={cn(
                    "flex cursor-not-allowed items-center gap-2.5 rounded-[12px] px-2.5 py-2 text-[13px] text-[#7f8b99]",
                    collapsed && "justify-center px-0",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
                  {collapsed ? null : (
                    <>
                      <span className="flex-1 truncate">{item.label}</span>
                      <span className="text-[10px] uppercase tracking-wide">{item.badge}</span>
                    </>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </nav>
  );
}

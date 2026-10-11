import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  BarChart3,
  Briefcase,
  Clock,
  GitBranch,
  LayoutDashboard,
  PauseCircle,
  Settings,
  Sparkles,
  Store,
  Users,
  Wrench,
} from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  disabled?: boolean;
  badge?: string;
};

export type NavGroup = {
  title: string;
  items: NavItem[];
};

export const navGroups: NavGroup[] = [
  {
    title: "Обзор",
    items: [{ href: "/dashboard", label: "Дашборд", icon: LayoutDashboard }],
  },
  {
    title: "Продажи",
    items: [
      { href: "/deals", label: "Сделки", icon: Briefcase },
      { href: "/pipelines", label: "Воронки", icon: GitBranch },
    ],
  },
  {
    title: "Контроль",
    items: [
      { href: "/overdue", label: "Просроченные", icon: Clock },
      { href: "/stalled", label: "Без следующего дела", icon: PauseCircle },
      { href: "/admin/sales-rules", label: "Регламент", icon: Settings },
    ],
  },
  {
    title: "Команда",
    items: [
      { href: "/managers", label: "Менеджеры", icon: Users },
      { href: "/manager-control", label: "Контроль менеджеров", icon: Clock },
    ],
  },
  {
    title: "Аналитика",
    items: [{ href: "/reports", label: "Отчёты", icon: BarChart3 }],
  },
  {
    title: "Система",
    items: [{ href: "/system", label: "Система", icon: Wrench }],
  },
];

export const futureNav: NavItem[] = [
  { href: "#avito", label: "Avito", icon: Store, disabled: true, badge: "Скоро" },
  { href: "#ai", label: "AI-анализ", icon: Sparkles, disabled: true, badge: "Скоро" },
];

/** @deprecated use navGroups — kept for any leftover imports */
export const mainNav: NavItem[] = navGroups.flatMap((g) => g.items);
export const placeholderNav: NavItem[] = futureNav;

export const problemNavIcon = AlertTriangle;

export const pageTitles: Record<string, string> = {
  "/dashboard": "Дашборд",
  "/deals": "Сделки",
  "/managers": "Менеджеры",
  "/manager-control": "Контроль менеджеров",
  "/pipelines": "Воронки",
  "/overdue": "Просроченные дела",
  "/stalled": "Без следующего дела",
  "/reports": "Отчёты",
  "/system": "Система",
  "/admin/sales-rules": "Регламент",
  "/settings/rules": "Правила",
};

export function resolvePageTitle(pathname: string): string {
  if (pageTitles[pathname]) return pageTitles[pathname];
  if (pathname.startsWith("/deals/")) return "Сделка";
  if (pathname.startsWith("/managers/")) return "Менеджер";
  if (pathname.startsWith("/manager-control/")) return "Контроль менеджера";
  for (const [path, title] of Object.entries(pageTitles)) {
    if (pathname.startsWith(path)) return title;
  }
  return "Focus Analytics";
}

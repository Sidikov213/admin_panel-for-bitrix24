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

export const mainNav: NavItem[] = [
  { href: "/dashboard", label: "Дашборд", icon: LayoutDashboard },
  { href: "/deals", label: "Сделки", icon: Briefcase },
  { href: "/managers", label: "Менеджеры", icon: Users },
  { href: "/pipelines", label: "Воронки", icon: GitBranch },
  { href: "/overdue", label: "Просроченные дела", icon: Clock },
  { href: "/stalled", label: "Без следующего дела", icon: PauseCircle },
  { href: "/reports", label: "Отчёты", icon: BarChart3 },
  { href: "/system", label: "Система", icon: Wrench },
];

export const placeholderNav: NavItem[] = [
  { href: "#avito", label: "Avito", icon: Store, disabled: true, badge: "В разработке" },
  { href: "#ai", label: "AI-анализ", icon: Sparkles, disabled: true, badge: "В разработке" },
  { href: "#settings", label: "Настройки", icon: Settings, disabled: true, badge: "В разработке" },
];

export const problemNavIcon = AlertTriangle;

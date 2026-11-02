import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  BarChart3,
  Briefcase,
  ClipboardCheck,
  Clock,
  GitBranch,
  LayoutDashboard,
  PauseCircle,
  Settings,
  Sparkles,
  Store,
  Target,
  Timer,
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
  { href: "/stalled", label: "Зависшие сделки", icon: PauseCircle },
  { href: "/reaction", label: "Скорость реакции", icon: Timer },
  { href: "/quality", label: "Качество карточек", icon: ClipboardCheck },
  { href: "/avito", label: "Avito", icon: Store },
  { href: "/ai", label: "ИИ-анализ", icon: Sparkles },
  { href: "/plan", label: "План / факт", icon: Target },
  { href: "/reports", label: "Отчёты", icon: BarChart3 },
  { href: "/system", label: "Система", icon: Wrench },
];

export const placeholderNav: NavItem[] = [
  { href: "#settings", label: "Настройки", icon: Settings, disabled: true, badge: "В разработке" },
];

export const problemNavIcon = AlertTriangle;

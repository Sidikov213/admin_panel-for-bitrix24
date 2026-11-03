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
};

export type NavGroup = { title: string; items: NavItem[] };

export const navGroups: NavGroup[] = [
  {
    title: "Обзор",
    items: [
      { href: "/dashboard", label: "Дашборд", icon: LayoutDashboard },
      { href: "/reports", label: "Отчёты", icon: BarChart3 },
      { href: "/ai", label: "ИИ-анализ", icon: Sparkles },
      { href: "/plan", label: "План / факт", icon: Target },
    ],
  },
  {
    title: "Контроль",
    items: [
      { href: "/overdue", label: "Просроченные дела", icon: Clock },
      { href: "/stalled", label: "Зависшие сделки", icon: PauseCircle },
      { href: "/reaction", label: "Скорость реакции", icon: Timer },
      { href: "/quality", label: "Качество карточек", icon: ClipboardCheck },
    ],
  },
  {
    title: "Данные",
    items: [
      { href: "/deals", label: "Сделки", icon: Briefcase },
      { href: "/managers", label: "Менеджеры", icon: Users },
      { href: "/pipelines", label: "Воронки", icon: GitBranch },
      { href: "/avito", label: "Avito", icon: Store },
    ],
  },
  { title: "Служебное", items: [{ href: "/system", label: "Система", icon: Wrench }] },
];

export const problemNavIcon = AlertTriangle;

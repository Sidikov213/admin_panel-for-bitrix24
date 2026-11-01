"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Briefcase,
  CalendarClock,
  ChevronRight,
  CircleDollarSign,
  Clock,
  History,
  ShieldAlert,
  Sparkles,
  Target,
  Trophy,
  Wallet,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { DataFreshness } from "@/components/common/data-freshness";
import { MetricCard } from "@/components/common/metric-card";
import {
  CATEGORY_AXIS_WIDTH,
  CATEGORY_LABEL_WIDTH,
  CategoryAxisTick,
  CategoryBarTooltip,
  categoryChartHeight,
} from "@/components/charts/category-axis-tick";
import { DeltaBadge } from "@/components/common/delta-badge";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { PeriodPicker, defaultPeriod, type PeriodValue } from "@/components/common/period-picker";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDashboard, useManagers } from "@/hooks/queries";
import { formatMoney, formatNumber } from "@/lib/format";
import type { AttentionCategory, MetricDelta, NamedCount } from "@/types/api";

function asNamedList(value: NamedCount[] | Record<string, number> | null | undefined): NamedCount[] {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  return Object.entries(value).map(([id, count]) => ({ name: id, count }));
}

function deltaOf(metrics: Record<string, MetricDelta> | undefined, key: string) {
  return metrics?.[key] ?? null;
}

function categoryAmount(cat: AttentionCategory) {
  return cat.items.reduce((sum, item) => sum + (Number(item.amount) || 0), 0);
}

const ATTENTION_HREF: Record<string, string> = {
  overdue_activities: "/overdue",
  overdue: "/overdue",
  no_future_activity: "/stalled?mode=no_future",
  without_future: "/stalled?mode=no_future",
  no_movement: "/stalled?mode=no_movement",
  without_movement: "/stalled?mode=no_movement",
  regulation: "/admin/sales-rules",
  violations: "/admin/sales-rules",
};

function attentionHref(key: string) {
  const k = key.toLowerCase();
  for (const [pattern, href] of Object.entries(ATTENTION_HREF)) {
    if (k.includes(pattern.replace(/_/g, "")) || k.includes(pattern)) return href;
  }
  if (k.includes("overdue") || k.includes("просроч")) return "/overdue";
  if (k.includes("future") || k.includes("следующ")) return "/stalled?mode=no_future";
  if (k.includes("movement") || k.includes("движен")) return "/stalled?mode=no_movement";
  if (k.includes("viol") || k.includes("регламент") || k.includes("rule")) return "/admin/sales-rules";
  return "/deals";
}

export function DashboardView() {
  const [period, setPeriod] = useState<PeriodValue>(defaultPeriod);
  const periodParams = {
    preset: period.preset === "custom" ? undefined : period.preset,
    period_start: period.from,
    period_end: period.to,
  };
  const dash = useDashboard(periodParams);
  const managers = useManagers(periodParams);

  const kpis = dash.data?.kpis;
  const charts = dash.data?.charts;
  const cmp = dash.data?.comparison?.metrics;
  const attention = dash.data?.attention;
  const planFact = dash.data?.plan_fact;
  const ruleKpis = dash.data?.rule_violations;

  const stageData = useMemo(
    () =>
      asNamedList(charts?.deals_by_stage)
        .sort((a, b) => b.count - a.count),
    [charts],
  );

  const series = charts?.series_daily ?? kpis?.series_daily ?? [];

  const managerRows = useMemo(() => {
    const rows = [...(managers.data ?? [])];
    rows.sort((a, b) => (b.sum_won_opportunity ?? 0) - (a.sum_won_opportunity ?? 0));
    return rows.slice(0, 8);
  }, [managers.data]);

  if (dash.isLoading && !kpis) return <PageLoading rows={6} />;
  if (dash.isError) return <ErrorState message="Не удалось загрузить дашборд." onRetry={() => void dash.refetch()} />;
  if (!kpis) return <EmptyState title="Нет данных" description="KPI пока недоступны." />;

  const objectiveCats = attention?.objective_signals?.categories
    ? (Object.entries(attention.objective_signals.categories) as [string, AttentionCategory][])
    : attention?.categories
      ? (Object.entries(attention.categories) as [string, AttentionCategory][])
      : [];
  const businessCats = attention?.business_rule_violations?.categories
    ? (Object.entries(attention.business_rule_violations.categories) as [string, AttentionCategory][])
    : [];

  const attentionRows: Array<{ key: string; label: string; count: number; amount: number; href: string }> = [];
  for (const [key, cat] of objectiveCats) {
    attentionRows.push({
      key: `obj-${key}`,
      label: cat.label,
      count: cat.count,
      amount: categoryAmount(cat),
      href: attentionHref(key + cat.label),
    });
  }
  if (businessCats.length) {
    const total = businessCats.reduce((s, [, c]) => s + c.count, 0);
    const amount = businessCats.reduce((s, [, c]) => s + categoryAmount(c), 0);
    attentionRows.push({
      key: "biz-violations",
      label: "Нарушения регламента",
      count: total,
      amount,
      href: "/admin/sales-rules",
    });
  } else {
    attentionRows.push({
      key: "biz-empty",
      label: "Нарушения регламента",
      count: ruleKpis?.open_violations ?? 0,
      amount: ruleKpis?.amount_under_violations ?? 0,
      href: "/admin/sales-rules",
    });
  }

  const wonDelta = deltaOf(cmp, "sum_won_opportunity");
  const moneyAtt = attention?.money_requiring_attention;

  const newSeries = series.map((point) => point.new);
  const wonSeries = series.map((point) => point.won);
  const stageBars = stageData.slice(0, 8).map((row) => row.count);

  return (
    <div className="section-stack">
      <section className="grid items-stretch gap-4 xl:grid-cols-[minmax(0,0.72fr)_minmax(0,1.28fr)]">
        <article className="panel flex min-w-0 flex-col p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-[13px] font-medium text-muted-foreground">Продажи</p>
              <p className="kpi-value-lg mt-2">{formatMoney(kpis.sum_won_opportunity)}</p>
              <div className="mt-1.5">
                <DeltaBadge delta={wonDelta} compact />
              </div>
            </div>
            <PeriodPicker value={period} onChange={setPeriod} compact />
          </div>
          <div className="mt-4 h-40 min-h-40">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={series} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="salesArea" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#0f766e" stopOpacity={0.22} />
                    <stop offset="100%" stopColor="#0f766e" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 12, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
                <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} width={32} />
                <Tooltip content={<CategoryBarTooltip />} />
                <Area type="monotone" dataKey="won" name="Выигранные" stroke="#0f766e" fill="url(#salesArea)" strokeWidth={2} dot={false} />
                <Area type="monotone" dataKey="new" name="Новые" stroke="#1d4ed8" fill="#1d4ed8" fillOpacity={0.06} strokeWidth={1.6} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 flex justify-end">
            <DataFreshness freshness={dash.data?.freshness} fallbackAt={kpis.computed_at} compact />
          </div>
        </article>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-2 2xl:grid-cols-3">
          <MetricCard
            label="Активных сделок"
            value={formatNumber(kpis.active_deals_count)}
            icon={Briefcase}
            tone={{ bg: "#e7f6f2", fg: "#0f766e" }}
            series={stageBars}
            chart="bar"
            footer={<DeltaBadge delta={deltaOf(cmp, "active_deals_count")} />}
          />
          <MetricCard
            label="В работе"
            value={formatMoney(kpis.sum_active_opportunity)}
            icon={CircleDollarSign}
            tone={{ bg: "#e8f1fb", fg: "#1d4ed8" }}
            footer={<DeltaBadge delta={deltaOf(cmp, "sum_active_opportunity")} />}
          />
          <MetricCard
            label="Новых"
            value={formatNumber(kpis.new_deals_count)}
            icon={Sparkles}
            tone={{ bg: "#e8f8ef", fg: "#15803d" }}
            series={newSeries}
            footer={<DeltaBadge delta={deltaOf(cmp, "new_deals_count")} />}
          />
          <MetricCard
            label="Выиграно"
            value={formatNumber(kpis.won_count)}
            icon={Trophy}
            tone={{ bg: "#fff4e8", fg: "#c2410c" }}
            series={wonSeries}
            footer={<DeltaBadge delta={deltaOf(cmp, "won_count")} />}
          />
          <MetricCard
            label="Проиграно"
            value={formatNumber(kpis.lost_count)}
            icon={XCircle}
            tone={{ bg: "#fdecec", fg: "#b42318" }}
            footer={<DeltaBadge delta={deltaOf(cmp, "lost_count")} />}
          />
        </div>
      </section>

      {planFact ? (
        <section className="relative overflow-hidden rounded-[18px] border border-[#f3e4cf] bg-[#fbf6ee] px-5 py-4">
          <div aria-hidden className="pointer-events-none absolute -right-6 -top-8 h-28 w-28 rounded-full bg-[#f3d7b0]/50" />
          <div className="relative flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] bg-[#fff] text-[#c2410c]">
                <Target className="h-4 w-4" />
              </span>
              <div>
                <p className="text-[16px] font-semibold tracking-tight">
                  {planFact.plan_set ? "План продаж" : "План продаж не задан"}
                </p>
                <p className="mt-0.5 text-[13px] text-[#7c6a58]">
                  {planFact.plan_set
                    ? `Факт ${formatMoney(planFact.fact)} из ${formatMoney(planFact.plan)}`
                    : `Факт за период: ${formatMoney(planFact.fact)}`}
                </p>
              </div>
            </div>
            {planFact.plan_set ? (
              <div className="w-full max-w-xs">
                <div className="mb-1 flex justify-between text-[12px] font-medium text-[#7c6a58]">
                  <span>Выполнение</span>
                  <span className="tabular-nums">{planFact.percent != null ? `${planFact.percent}%` : "—"}</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-white/80">
                  <div
                    className="h-full rounded-full bg-[#c2410c]"
                    style={{ width: `${Math.min(100, Math.max(0, planFact.percent ?? 0))}%` }}
                  />
                </div>
              </div>
            ) : (
              <Link
                href="/system"
                className="inline-flex h-10 items-center rounded-[12px] bg-[#1c2430] px-4 text-[13px] font-medium text-white"
              >
                Настроить
              </Link>
            )}
          </div>
        </section>
      ) : null}

      <section className="panel">
        <div className="panel-header">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-[10px] bg-[#fff4e8] text-[#c2410c]">
              <ShieldAlert className="h-4 w-4" />
            </span>
            <h2 className="section-title">Требует внимания</h2>
          </div>
          <p className="text-[13px] font-medium tabular-nums text-muted-foreground">
            {moneyAtt
              ? `${formatNumber(moneyAtt.deals_count)} сделок · ${formatMoney(moneyAtt.amount)}`
              : `${formatNumber(kpis.deals_requiring_attention_count ?? 0)} сделок · ${formatMoney(kpis.money_requiring_attention ?? 0)}`}
          </p>
        </div>
        <ul>
          {attentionRows.map((row) => {
            const tone = attentionTone(row.label);
            const Icon = tone.icon;
            return (
              <li key={row.key} className="border-t border-border first:border-t-0">
                <Link href={row.href} className="interactive-row flex min-h-[52px] items-center gap-3 px-4 py-2 text-[14px]">
                  <span
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px]"
                    style={{ background: tone.bg, color: tone.fg }}
                  >
                    <Icon className="h-4 w-4" />
                  </span>
                  <span className="min-w-0 flex-1 truncate text-foreground">{row.label}</span>
                  <span className="w-12 text-right font-semibold tabular-nums">
                    {row.count > 0 ? formatNumber(row.count) : "—"}
                  </span>
                  <span className="hidden w-32 text-right tabular-nums text-muted-foreground sm:inline">
                    {row.count > 0 ? formatMoney(row.amount) : "—"}
                  </span>
                  <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                </Link>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="grid gap-4">
        <div className="panel panel-pad min-w-0 overflow-hidden">
          <div className="mb-4 flex items-baseline justify-between gap-2">
            <h2 className="section-title">Распределение активных</h2>
            <span className="meta">по этапам</span>
          </div>
          <div className="min-w-0" style={{ height: stageData.length === 0 ? undefined : categoryChartHeight(stageData.length) }}>
            {stageData.length === 0 ? (
              <p className="text-[13px] text-muted-foreground">Нет данных по этапам.</p>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={stageData} layout="vertical" margin={{ left: 8, right: 12, top: 8, bottom: 4 }} barCategoryGap={10}>
                  <CartesianGrid stroke="var(--border)" horizontal={false} strokeDasharray="0" />
                  <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={CATEGORY_AXIS_WIDTH}
                    interval={0}
                    tick={<CategoryAxisTick maxWidth={CATEGORY_LABEL_WIDTH} />}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip content={<CategoryBarTooltip />} />
                  <Bar dataKey="count" name="Сделки" fill="var(--primary)" radius={[0, 3, 3, 0]} barSize={16} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </section>

      {/* Managers compact */}
      <section className="panel">
        <div className="panel-header">
          <h2 className="section-title">Менеджеры</h2>
          <Link href="/managers" className="text-[12px] font-medium text-primary hover:underline">
            Все менеджеры
          </Link>
        </div>
        <div className="overflow-x-auto">
          <Table className="data-table">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-4">Менеджер</TableHead>
                <TableHead className="text-right">Продажи</TableHead>
                <TableHead className="text-right">Активные</TableHead>
                <TableHead className="text-right">Просрочки</TableHead>
                <TableHead className="text-right">Без следующего</TableHead>
                <TableHead className="pr-4 text-right">Динамика</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {managerRows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-6 text-center text-muted-foreground">
                    Нет данных по менеджерам
                  </TableCell>
                </TableRow>
              ) : (
                managerRows.map((m) => (
                  <TableRow key={m.id} className="interactive-row">
                    <TableCell className="pl-4">
                      <Link className="font-medium text-foreground hover:text-primary" href={`/managers/${m.id}`}>
                        {[m.name, m.last_name].filter(Boolean).join(" ") || `ID ${m.id}`}
                      </Link>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatMoney(m.sum_won_opportunity)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatNumber(m.active_deals_count ?? 0)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatNumber(m.overdue_activities_unique ?? 0)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatNumber(m.deals_without_future_activity_count ?? 0)}
                    </TableCell>
                    <TableCell className="pr-4 text-right">
                      <DeltaBadge delta={m.new_deals_delta} />
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </section>
    </div>
  );
}

function attentionTone(label: string): { icon: LucideIcon; bg: string; fg: string } {
  const text = label.toLowerCase();
  if (text.includes("регламент")) return { icon: ShieldAlert, bg: "#e7f6f2", fg: "#0f766e" };
  if (text.includes("просроч")) return { icon: Clock, bg: "#fdecec", fg: "#b42318" };
  if (text.includes("деньг") || text.includes("завис")) return { icon: Wallet, bg: "#e8f1fb", fg: "#1d4ed8" };
  if (text.includes("движен") || text.includes("отсутств") || text.includes("потер")) {
    return { icon: History, bg: "#fff4e8", fg: "#c2410c" };
  }
  return { icon: CalendarClock, bg: "#e7f6f2", fg: "#0f766e" };
}

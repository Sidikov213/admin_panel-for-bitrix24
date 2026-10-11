"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { DataFreshness } from "@/components/common/data-freshness";
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
        .sort((a, b) => b.count - a.count)
        .slice(0, 8),
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

  return (
    <div className="section-stack">
      {/* Toolbar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[13px] text-muted-foreground">Отдел продаж · период сравнения с предыдущим</p>
        <div className="flex flex-wrap items-center gap-3">
          <PeriodPicker value={period} onChange={setPeriod} compact />
          <DataFreshness freshness={dash.data?.freshness} fallbackAt={kpis.computed_at} compact />
        </div>
      </div>

      {/* Hero + secondary strip */}
      <section className="panel panel-pad">
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1.95fr)] lg:items-end">
          <div>
            <p className="meta">Продажи</p>
            <p className="kpi-value-lg mt-1.5">{formatMoney(kpis.sum_won_opportunity)}</p>
            <div className="mt-1.5">
              <DeltaBadge delta={wonDelta} compact />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-x-5 gap-y-4 border-t border-border pt-4 sm:grid-cols-5 lg:border-t-0 lg:border-l lg:pl-6 lg:pt-0">
            <StripMetric
              label="Активных сделок"
              value={formatNumber(kpis.active_deals_count)}
              delta={deltaOf(cmp, "active_deals_count")}
            />
            <StripMetric
              label="В работе"
              value={formatMoney(kpis.sum_active_opportunity)}
              delta={deltaOf(cmp, "sum_active_opportunity")}
            />
            <StripMetric
              label="Новых"
              value={formatNumber(kpis.new_deals_count)}
              delta={deltaOf(cmp, "new_deals_count")}
            />
            <StripMetric label="Выиграно" value={formatNumber(kpis.won_count)} delta={deltaOf(cmp, "won_count")} />
            <StripMetric label="Проиграно" value={formatNumber(kpis.lost_count)} delta={deltaOf(cmp, "lost_count")} />
          </div>
        </div>
      </section>

      {/* Plan / fact — compact */}
      {planFact ? (
        <section className="panel panel-pad">
          {planFact.plan_set ? (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div className="grid grid-cols-3 gap-6 text-[13px]">
                <div>
                  <p className="meta">План</p>
                  <p className="mt-0.5 text-[15px] font-semibold tabular-nums">{formatMoney(planFact.plan)}</p>
                </div>
                <div>
                  <p className="meta">Факт</p>
                  <p className="mt-0.5 text-[15px] font-semibold tabular-nums">{formatMoney(planFact.fact)}</p>
                </div>
                <div>
                  <p className="meta">Выполнение</p>
                  <p className="mt-0.5 text-[15px] font-semibold tabular-nums">
                    {planFact.percent != null ? `${planFact.percent}%` : "—"}
                  </p>
                </div>
              </div>
              <div className="w-full max-w-xs">
                <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary transition-[width] duration-200"
                    style={{ width: `${Math.min(100, Math.max(0, planFact.percent ?? 0))}%` }}
                  />
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="section-title">План продаж не задан</p>
                <p className="meta mt-0.5">Факт за период: {formatMoney(planFact.fact)}</p>
              </div>
              <Link
                href="/system"
                className="rounded-md border border-border bg-background px-3 py-1.5 text-[13px] font-medium text-foreground transition-colors hover:bg-muted"
              >
                Настроить
              </Link>
            </div>
          )}
        </section>
      ) : null}

      {/* Attention — central */}
      <section className="panel">
        <div className="panel-header">
          <h2 className="section-title">Требует внимания</h2>
          <p className="text-[13px] tabular-nums text-muted-foreground">
            {moneyAtt
              ? `${formatNumber(moneyAtt.deals_count)} сделок · ${formatMoney(moneyAtt.amount)}`
              : `${formatNumber(kpis.deals_requiring_attention_count ?? 0)} сделок · ${formatMoney(kpis.money_requiring_attention ?? 0)}`}
          </p>
        </div>
        <ul>
          {attentionRows.map((row, i) => (
            <li key={row.key} className={i > 0 ? "border-t border-border" : ""}>
              <Link
                href={row.href}
                className="interactive-row flex items-center gap-4 px-4 py-2.5 text-[13px]"
              >
                <span className="min-w-0 flex-1 truncate text-foreground">{row.label}</span>
                <span className="w-14 text-right font-medium tabular-nums">
                  {row.count > 0 ? formatNumber(row.count) : "—"}
                </span>
                <span className="w-28 text-right tabular-nums text-muted-foreground">
                  {row.count > 0 ? formatMoney(row.amount) : "—"}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      {/* Charts */}
      <section className="grid gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="panel panel-pad">
          <div className="mb-4 flex items-baseline justify-between gap-2">
            <h2 className="section-title">Продажи / динамика</h2>
            <span className="meta">новые · выигранные</span>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="0" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} width={32} />
                <Tooltip
                  contentStyle={{
                    borderRadius: 8,
                    border: "1px solid var(--border)",
                    fontSize: 12,
                    boxShadow: "none",
                  }}
                />
                <Line type="monotone" dataKey="new" name="Новые" stroke="var(--primary)" strokeWidth={1.75} dot={false} />
                <Line type="monotone" dataKey="won" name="Выигранные" stroke="#5a5a56" strokeWidth={1.75} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="panel panel-pad">
          <div className="mb-4 flex items-baseline justify-between gap-2">
            <h2 className="section-title">Распределение активных</h2>
            <span className="meta">по этапам</span>
          </div>
          <div className="h-64">
            {stageData.length === 0 ? (
              <p className="text-[13px] text-muted-foreground">Нет данных по этапам.</p>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={stageData} layout="vertical" margin={{ left: 4, right: 8, top: 4, bottom: 0 }}>
                  <CartesianGrid stroke="var(--border)" horizontal={false} strokeDasharray="0" />
                  <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={100}
                    tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      borderRadius: 8,
                      border: "1px solid var(--border)",
                      fontSize: 12,
                      boxShadow: "none",
                    }}
                  />
                  <Bar dataKey="count" name="Сделки" fill="var(--primary)" radius={[0, 3, 3, 0]} barSize={14} />
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

function StripMetric({
  label,
  value,
  delta,
}: {
  label: string;
  value: string;
  delta?: MetricDelta | null;
}) {
  return (
    <div className="min-w-0">
      <p className="meta truncate">{label}</p>
      <p className="mt-1 text-[1.125rem] font-semibold tabular-nums tracking-tight">{value}</p>
      {delta ? (
        <div className="mt-0.5">
          <DeltaBadge delta={delta} />
        </div>
      ) : null}
    </div>
  );
}

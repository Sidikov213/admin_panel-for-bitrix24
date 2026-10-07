"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { KpiCard } from "@/components/common/kpi-card";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { PeriodPicker, defaultPeriod, type PeriodValue } from "@/components/common/period-picker";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDashboard, useSystem } from "@/hooks/queries";
import { formatDateTime, formatMoney, formatNumber } from "@/lib/format";
import type { NamedCount, PipelineCount } from "@/types/api";

const CHART_COLORS = ["#0f766e", "#0369a1", "#b45309", "#be123c", "#4d7c0f", "#0e7490"];

function asNamedList(value: NamedCount[] | Record<string, number> | null | undefined): NamedCount[] {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  return Object.entries(value).map(([id, count]) => ({ name: id, count }));
}

export function DashboardView() {
  const [period, setPeriod] = useState<PeriodValue>(defaultPeriod);
  const dash = useDashboard(period.from, period.to);
  const system = useSystem();

  const kpis = dash.data?.kpis;
  const charts = dash.data?.charts;

  const pipelineData = useMemo(() => {
    const named = charts?.deals_by_pipeline as PipelineCount[] | undefined;
    if (named?.length) return named.map((p) => ({ name: p.name, value: p.count }));
    return asNamedList(charts?.deals_by_stage).map((s) => ({ name: s.name, value: s.count }));
  }, [charts]);

  const managerData = useMemo(
    () =>
      asNamedList(charts?.deals_by_manager)
        .sort((a, b) => b.count - a.count)
        .slice(0, 8),
    [charts],
  );

  const series = charts?.series_daily ?? kpis?.series_daily ?? [];

  if (dash.isLoading && !kpis) return <PageLoading rows={6} />;
  if (dash.isError) return <ErrorState message="Не удалось загрузить дашборд." onRetry={() => void dash.refetch()} />;

  const syncStale = Boolean(system.data?.data_may_be_stale || (system.data && !system.data.bitrix_reachable));
  const lastSync =
    dash.data?.sync?.latest_run_finished_at ||
    (typeof system.data?.last_deals_sync === "object" && system.data?.last_deals_sync?.at) ||
    null;

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="font-serif text-3xl font-semibold tracking-tight">Дашборд</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Что сейчас происходит в отделе продаж · {period.from} — {period.to}
          </p>
        </div>
        <PeriodPicker value={period} onChange={setPeriod} />
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <span>
          Обновление данных:{" "}
          <strong className="font-medium text-foreground">{formatDateTime(lastSync || kpis?.computed_at)}</strong>
        </span>
        {system.data?.latest_sync_run ? (
          <Badge variant={syncStale ? "warning" : "secondary"}>
            Синхронизация: {system.data.latest_sync_run.status}
          </Badge>
        ) : (
          <Badge variant="secondary">Синхронизация ещё не выполнялась</Badge>
        )}
        {syncStale ? <Badge variant="warning">Данные могут быть устаревшими</Badge> : null}
        {system.data?.demo_mode ? <Badge variant="outline">DEMO</Badge> : null}
      </div>

      {kpis?.data_quality?.note ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {kpis.data_quality.note}
        </p>
      ) : null}

      {kpis ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <KpiCard
            title="Новые сделки"
            value={formatNumber(kpis.new_deals_count)}
            href="/deals"
            source={kpis.definitions?.new_deals_count?.source}
            formula={kpis.definitions?.new_deals_count?.formula}
            freshness={kpis.computed_at}
          />
          <KpiCard
            title="Активные сделки"
            value={formatNumber(kpis.active_deals_count)}
            href="/deals?closed=false"
            source={kpis.definitions?.active_deals_count?.source}
            formula={kpis.definitions?.active_deals_count?.formula}
            freshness={kpis.computed_at}
          />
          <KpiCard
            title="Успешно закрыто"
            value={formatNumber(kpis.won_count)}
            href="/deals?closed=true"
            source={kpis.definitions?.won_count?.source}
            formula={kpis.definitions?.won_count?.formula}
            freshness={kpis.computed_at}
          />
          <KpiCard
            title="Сумма в работе"
            value={formatMoney(kpis.sum_active_opportunity)}
            href="/deals?closed=false"
            source={kpis.definitions?.sum_active_opportunity?.source}
            formula={kpis.definitions?.sum_active_opportunity?.formula}
            freshness={kpis.computed_at}
          />
          <KpiCard
            title="Просроченные дела"
            value={formatNumber(kpis.overdue_activities_unique)}
            href="/overdue"
            source={kpis.definitions?.overdue_activities_unique?.source}
            formula={kpis.definitions?.overdue_activities_unique?.formula}
            freshness={kpis.computed_at}
          />
          <KpiCard
            title={kpis.deals_without_future_activity_label ?? "Без следующего дела"}
            value={formatNumber(kpis.deals_without_future_activity_count)}
            href="/stalled"
            source={kpis.definitions?.deals_without_future_activity_count?.source}
            formula={kpis.definitions?.deals_without_future_activity_count?.formula}
            freshness={kpis.computed_at}
          />
        </div>
      ) : (
        <EmptyState title="Нет KPI" description="API не вернул метрики за период." />
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Новые и успешно закрытые</CardTitle>
            <CardDescription>Динамика по дням (Europe/Moscow)</CardDescription>
          </CardHeader>
          <CardContent className="h-72">
            {!series.length || series.every((d) => d.new === 0 && d.won === 0) ? (
              <EmptyState title="Нет данных для графика" />
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={24} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="new" name="Новые" stroke="#0f766e" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="won" name="Закрыто" stroke="#0369a1" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Распределение по воронкам</CardTitle>
            <CardDescription>Активные сделки</CardDescription>
          </CardHeader>
          <CardContent className="h-72">
            {pipelineData.length === 0 ? (
              <EmptyState title="Нет активных сделок" />
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={pipelineData} dataKey="value" nameKey="name" innerRadius={50} outerRadius={90} paddingAngle={2}>
                    {pipelineData.map((_, i) => (
                      <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Менеджеры</CardTitle>
          <CardDescription>Активные сделки по ответственным</CardDescription>
        </CardHeader>
        <CardContent className="h-64">
          {managerData.length === 0 ? (
            <EmptyState title="Нет данных по менеджерам" />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={managerData} layout="vertical" margin={{ left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--border)" />
                <XAxis type="number" allowDecimals={false} />
                <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="count" fill="#0369a1" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Проблемные сделки</CardTitle>
            <CardDescription>Без следующего дела или наблюдаемый застой</CardDescription>
          </CardHeader>
          <CardContent>
            {(dash.data?.problem_deals ?? []).length === 0 ? (
              <EmptyState title="Проблемных сделок нет" />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Сделка</TableHead>
                    <TableHead>Флаги</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(dash.data?.problem_deals ?? []).slice(0, 10).map((d) => (
                    <TableRow key={d.deal_id}>
                      <TableCell>
                        <Link href={`/deals/${d.deal_id}`} className="font-medium text-primary hover:underline">
                          {d.title}
                        </Link>
                        {d.manager ? <p className="text-xs text-muted-foreground">{d.manager}</p> : null}
                      </TableCell>
                      <TableCell className="space-x-1">
                        {d.no_future_activity ? <Badge variant="warning">Нет следующего дела</Badge> : null}
                        {d.stalled ? <Badge variant="destructive">Наблюдаемый застой</Badge> : null}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Последние изменения</CardTitle>
            <CardDescription>Наблюдаемая история (время обнаружения при polling)</CardDescription>
          </CardHeader>
          <CardContent>
            {(dash.data?.recent_changes ?? []).length === 0 ? (
              <EmptyState title="Изменений пока нет" />
            ) : (
              <ul className="divide-y divide-border">
                {(dash.data?.recent_changes ?? []).slice(0, 8).map((c, idx) => (
                  <li key={`${c.deal_id}-${c.field_name}-${idx}`} className="py-3 text-sm">
                    <Link href={`/deals/${c.deal_id}`} className="font-medium text-primary hover:underline">
                      Сделка #{c.deal_id}
                    </Link>
                    <p className="text-muted-foreground">
                      {c.field_name}: {c.old_value ?? "—"} → {c.new_value ?? "—"}
                    </p>
                    <p className="text-xs text-muted-foreground">{formatDateTime(c.observed_at)}</p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

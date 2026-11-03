"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";
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
import {
  PeriodPicker,
  defaultPeriod,
  periodFromPreset,
  type PeriodPreset,
  type PeriodValue,
} from "@/components/common/period-picker";
import { PlanProgressCard } from "@/components/plan/plan-progress-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDashboard, useManagers, usePipelines, useSystem, useTargetsProgress } from "@/hooks/queries";
import { formatDate, formatDateTime, formatMoney, formatNumber, managerName } from "@/lib/format";
import type { NamedCount, PipelineCount } from "@/types/api";

const CHART_COLORS = ["#0f766e", "#0369a1", "#b45309", "#be123c", "#4d7c0f", "#0e7490"];

function asNamedList(value: NamedCount[] | Record<string, number> | null | undefined): NamedCount[] {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  return Object.entries(value).map(([id, count]) => ({ name: id, count }));
}

/** Filters live in the URL so a filtered dashboard can be bookmarked or sent as a link. */
function useDashboardFilters() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const preset = (searchParams.get("preset") as PeriodPreset | null) ?? "month";
  const fallback = preset === "custom" ? defaultPeriod() : { preset, ...periodFromPreset(preset) };
  const period: PeriodValue = {
    preset,
    from: preset === "custom" ? (searchParams.get("from") ?? fallback.from) : fallback.from,
    to: preset === "custom" ? (searchParams.get("to") ?? fallback.to) : fallback.to,
  };
  const pipelineId = searchParams.get("pipeline") ? Number(searchParams.get("pipeline")) : undefined;
  const managerId = searchParams.get("manager") ? Number(searchParams.get("manager")) : undefined;

  const update = (patch: Record<string, string | number | undefined>) => {
    const params = new URLSearchParams(searchParams.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined || v === "") params.delete(k);
      else params.set(k, String(v));
    }
    const qs = params.toString();
    router.replace(qs ? `/dashboard?${qs}` : "/dashboard", { scroll: false });
  };

  return {
    period,
    pipelineId,
    managerId,
    setPeriod: (p: PeriodValue) =>
      update(p.preset === "custom" ? { preset: "custom", from: p.from, to: p.to } : { preset: p.preset === "month" ? undefined : p.preset, from: undefined, to: undefined }),
    setPipeline: (id: number | undefined) => update({ pipeline: id }),
    setManager: (id: number | undefined) => update({ manager: id }),
    reset: () => router.replace("/dashboard", { scroll: false }),
  };
}

/** Link to the deal list showing exactly the deals behind a KPI. */
function dealsHref(scope: { pipelineId?: number; managerId?: number }, params: Record<string, string | boolean>) {
  const q = new URLSearchParams();
  if (scope.pipelineId !== undefined) q.set("category_id", String(scope.pipelineId));
  if (scope.managerId !== undefined) q.set("manager_id", String(scope.managerId));
  for (const [k, v] of Object.entries(params)) q.set(k, String(v));
  return `/deals?${q.toString()}`;
}

const filterSelectClass =
  "flex h-10 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function DashboardView() {
  const filters = useDashboardFilters();
  const { period, pipelineId, managerId } = filters;
  const dash = useDashboard({ period_start: period.from, period_end: period.to, pipeline_id: pipelineId, manager_id: managerId });
  const system = useSystem();
  const pipelines = usePipelines();
  const managers = useManagers();
  const plan = useTargetsProgress(true);
  // Manager filter → that manager's plan; otherwise the department plan.
  // Shortest active target wins (a month plan beats the year plan).
  const shownPlan = (plan.data?.items ?? [])
    .filter((p) => (managerId !== undefined ? p.manager_id === managerId : p.manager_id === null))
    .sort((a, b) => a.days_total - b.days_total)[0];
  const scope = { pipelineId, managerId };
  const cmp = dash.data?.comparison?.metrics;
  const sortedManagers = (managers.data ?? []).slice().sort((a, b) => managerName(a).localeCompare(managerName(b)));
  const filtered = pipelineId !== undefined || managerId !== undefined;

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
      <div className="space-y-4">
        <div>
          <h1 className="font-serif text-3xl font-semibold tracking-tight">Дашборд</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Что сейчас происходит в отделе продаж · {formatDate(period.from)} — {formatDate(period.to)}
            {dash.data?.comparison ? (
              <>
                {" "}
                · сравнение с {formatDate(dash.data.comparison.period_start)} — {formatDate(dash.data.comparison.period_end)}
              </>
            ) : null}
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <PeriodPicker value={period} onChange={filters.setPeriod} />
          <div className="w-full space-y-1.5 sm:w-48">
            <Label htmlFor="dash-pipeline" className="block text-xs text-muted-foreground">
              Воронка
            </Label>
            <select
              id="dash-pipeline"
              className={filterSelectClass}
              value={pipelineId ?? ""}
              onChange={(e) => filters.setPipeline(e.target.value ? Number(e.target.value) : undefined)}
            >
              <option value="">Все воронки</option>
              {(pipelines.data ?? []).map((p) => (
                <option key={p.id} value={String(p.bitrix_id)}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="w-full space-y-1.5 sm:w-52">
            <Label htmlFor="dash-manager" className="block text-xs text-muted-foreground">
              Менеджер
            </Label>
            <select
              id="dash-manager"
              className={filterSelectClass}
              value={managerId ?? ""}
              onChange={(e) => filters.setManager(e.target.value ? Number(e.target.value) : undefined)}
            >
              <option value="">Все менеджеры</option>
              {sortedManagers.map((m) => (
                <option key={m.id} value={m.id}>
                  {managerName(m)}
                </option>
              ))}
            </select>
          </div>
          {filtered ? (
            <Button variant="ghost" size="sm" className="h-10" onClick={filters.reset}>
              Сбросить
            </Button>
          ) : null}
          {dash.isFetching && kpis ? <span className="h-10 text-sm leading-10 text-muted-foreground">Обновляем…</span> : null}
        </div>
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

      {shownPlan ? (
        <Link href="/plan" className="block max-w-xl">
          <PlanProgressCard p={shownPlan} compact />
        </Link>
      ) : null}

      {kpis ? (
        <div className="space-y-2">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              title="Новые сделки"
              value={formatNumber(kpis.new_deals_count)}
              href={dealsHref(scope, { created_from: period.from, created_to: period.to })}
              delta={cmp?.new_deals_count}
              source={kpis.definitions?.new_deals_count?.source}
              formula={kpis.definitions?.new_deals_count?.formula}
              freshness={kpis.computed_at}
            />
            <KpiCard
              title="Успешно закрыто"
              value={formatNumber(kpis.won_count)}
              href={dealsHref(scope, { outcome: "won", closed_from: period.from, closed_to: period.to })}
              delta={cmp?.won_count}
              source={kpis.definitions?.won_count?.source}
              formula={kpis.definitions?.won_count?.formula}
              freshness={kpis.computed_at}
            />
            <KpiCard
              title="Сумма выигранных"
              value={formatMoney(kpis.sum_won_opportunity)}
              href={dealsHref(scope, {
                outcome: "won",
                closed_from: period.from,
                closed_to: period.to,
                sort_by: "opportunity",
                sort_dir: "desc",
              })}
              delta={cmp?.sum_won_opportunity}
              formatPrevious={(v) => formatMoney(v)}
              source={kpis.definitions?.sum_won_opportunity?.source}
              formula={kpis.definitions?.sum_won_opportunity?.formula}
              freshness={kpis.computed_at}
            />
            <KpiCard
              title="Проиграно"
              value={formatNumber(kpis.lost_count)}
              href={dealsHref(scope, { outcome: "lost", closed_from: period.from, closed_to: period.to })}
              delta={cmp?.lost_count}
              higherIsBetter={false}
              source={kpis.definitions?.lost_count?.source}
              formula={kpis.definitions?.lost_count?.formula}
              freshness={kpis.computed_at}
            />
            <KpiCard
              title="Активные сделки"
              value={formatNumber(kpis.active_deals_count)}
              href={dealsHref(scope, { closed: false })}
              hint="на сейчас"
              source={kpis.definitions?.active_deals_count?.source}
              formula={kpis.definitions?.active_deals_count?.formula}
              freshness={kpis.computed_at}
            />
            <KpiCard
              title="Сумма в работе"
              value={formatMoney(kpis.sum_active_opportunity)}
              href={dealsHref(scope, { closed: false, sort_by: "opportunity", sort_dir: "desc" })}
              hint="на сейчас"
              source={kpis.definitions?.sum_active_opportunity?.source}
              formula={kpis.definitions?.sum_active_opportunity?.formula}
              freshness={kpis.computed_at}
            />
            <KpiCard
              title="Просроченные дела"
              value={formatNumber(kpis.overdue_activities_unique)}
              href={dealsHref(scope, { overdue: true })}
              hint="по клику — сделки, у которых есть просроченные дела"
              source={kpis.definitions?.overdue_activities_unique?.source}
              formula={kpis.definitions?.overdue_activities_unique?.formula}
              freshness={kpis.computed_at}
            />
            <KpiCard
              title={kpis.deals_without_future_activity_label ?? "Без следующего дела"}
              value={formatNumber(kpis.deals_without_future_activity_count)}
              href={dealsHref(scope, { closed: false, has_future_activity: false, sort_by: "opportunity", sort_dir: "desc" })}
              source={kpis.definitions?.deals_without_future_activity_count?.source}
              formula={kpis.definitions?.deals_without_future_activity_count?.formula}
              freshness={kpis.computed_at}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            Нажмите на карточку, чтобы открыть список этих сделок. Сравнение — с предыдущим периодом такой же длины;
            «Активные», «Сумма в работе» и просрочки — состояние на сейчас, без сравнения.
          </p>
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
          <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0">
            <div className="space-y-1.5">
              <CardTitle>Проблемные сделки</CardTitle>
              <CardDescription>Без следующего дела, сначала самые крупные</CardDescription>
            </div>
            <Link
              href={dealsHref(scope, { closed: false, has_future_activity: false, sort_by: "opportunity", sort_dir: "desc" })}
              className="shrink-0 text-sm text-primary hover:underline"
            >
              Все →
            </Link>
          </CardHeader>
          <CardContent>
            {(dash.data?.problem_deals ?? []).length === 0 ? (
              <EmptyState title="Проблемных сделок нет" />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Сделка</TableHead>
                    <TableHead>Сумма</TableHead>
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
                        <p className="text-xs text-muted-foreground">
                          {[d.stage, d.manager].filter(Boolean).join(" · ")}
                        </p>
                      </TableCell>
                      <TableCell className="whitespace-nowrap">{formatMoney(d.opportunity)}</TableCell>
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
                      {c.deal_title || `Сделка #${c.deal_id}`}
                    </Link>
                    <p className="text-muted-foreground">
                      {c.field_label ?? c.field_name}: {c.old_label ?? c.old_value ?? "—"} → {c.new_label ?? c.new_value ?? "—"}
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

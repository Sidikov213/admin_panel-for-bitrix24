"use client";

import { ChevronDown, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
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
import { formatDate, formatDateTime, formatDuration, formatMoney, formatNumber, formatPercent, managerName } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DashboardResponse, NamedCount, PipelineCount, SystemStatus } from "@/types/api";

const NEW_COLOR = "#0f766e";
const WON_COLOR = "#d97706";
const shortDate = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" });

function dayLabel(iso: string) {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : shortDate.format(d).replace(".", "");
}

/** Share of won among deals closed in the period. */
function conversion(won: number, lost: number): number | null {
  return won + lost ? Math.round((won / (won + lost)) * 1000) / 10 : null;
}

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
  "flex h-10 w-full appearance-none rounded-lg border border-input bg-background py-2 pl-3 pr-9 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** Native select that looks like the period picker next to it. */
function FilterSelect(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative">
      <select {...props} className={filterSelectClass} />
      <ChevronDown className="pointer-events-none absolute right-3 top-3 h-4 w-4 opacity-50" aria-hidden />
    </div>
  );
}

/** One line instead of three contradicting badges. */
function DataStatus({ system, lastSync, computedAt }: { system?: SystemStatus; lastSync: string | null; computedAt?: string }) {
  if (!system) return null;
  if (!system.bitrix_configured) {
    return (
      <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-900">
        Bitrix24 не подключён — показаны сохранённые в панели данные, а не живые.
        {system.demo_mode ? " Включён демо-режим." : ""}
      </p>
    );
  }
  if (system.sync_stalled) {
    return (
      <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-900">
        {system.stale_note || "Синхронизация с Bitrix24 остановилась — цифры устарели."}
        {lastSync ? (
          <>
            {" "}
            Последнее обновление: <strong className="font-medium">{formatDateTime(lastSync)}</strong>.
          </>
        ) : null}
      </p>
    );
  }
  const stale = system.data_may_be_stale || !system.bitrix_reachable;
  return (
    <p className={cn("text-sm", stale ? "text-amber-800" : "text-muted-foreground")}>
      {stale ? "Bitrix24 сейчас недоступен — данные на " : "Данные из Bitrix24 на "}
      <strong className="font-medium text-foreground">{formatDateTime(lastSync || computedAt)}</strong>
      {stale ? ", цифры могут быть устаревшими." : ""}
    </p>
  );
}

type Tone = "bad" | "warn" | "ok";

function AttentionTile({ label, value, href, note, tone }: { label: string; value: string; href: string; note?: string; tone: Tone }) {
  return (
    <Link
      href={href}
      className={cn(
        "group block rounded-xl border p-4 transition-shadow hover:shadow-md",
        tone === "bad" && "border-red-200 bg-red-50/70",
        tone === "warn" && "border-amber-200 bg-amber-50/70",
        tone === "ok" && "border-emerald-200 bg-emerald-50/60",
      )}
    >
      <p className="flex items-center justify-between gap-2 text-sm text-muted-foreground">
        {label}
        <span aria-hidden className="transition-transform group-hover:translate-x-0.5">
          →
        </span>
      </p>
      <p
        className={cn(
          "font-serif text-3xl font-semibold",
          tone === "bad" && "text-red-800",
          tone === "warn" && "text-amber-800",
          tone === "ok" && "text-emerald-800",
        )}
      >
        {value}
      </p>
      {note ? <p className="mt-1 text-xs text-muted-foreground">{note}</p> : null}
    </Link>
  );
}

function AttentionBlock({
  a,
  overdueActivities,
  href,
}: {
  a: NonNullable<DashboardResponse["attention"]>;
  overdueActivities?: number;
  href: (p: Record<string, string | boolean>) => string;
}) {
  // A few deals without a next activity is a warning; any overdue or stuck deal is a problem
  const tone = (n: number, badFrom = 1): Tone => (n === 0 ? "ok" : n >= badFrom ? "bad" : "warn");
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle>Требует внимания</CardTitle>
        <CardDescription>Состояние на сейчас. Нажмите на плитку, чтобы открыть список.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <AttentionTile
            label="Сделки с просрочкой"
            value={formatNumber(a.overdue_deals)}
            href={href({ overdue: true })}
            note={overdueActivities ? `просроченных дел: ${formatNumber(overdueActivities)}` : undefined}
            tone={tone(a.overdue_deals)}
          />
          <AttentionTile label="Зависшие сделки" value={formatNumber(a.stuck)} href="/stalled" note="дольше срока стадии" tone={tone(a.stuck)} />
          <AttentionTile
            label="Без следующего дела"
            value={formatNumber(a.no_next_activity)}
            href={href({ closed: false, has_future_activity: false, sort_by: "opportunity", sort_dir: "desc" })}
            note="по регламенту дело обязательно"
            tone={tone(a.no_next_activity, 5)}
          />
          {a.avito ? (
            <AttentionTile
              label="Avito без ответа"
              value={formatNumber(a.avito.unanswered)}
              href="/avito"
              note={a.avito.late ? `из них дольше нормы: ${a.avito.late}` : "все в пределах нормы"}
              tone={a.avito.late ? "bad" : a.avito.unanswered ? "warn" : "ok"}
            />
          ) : null}
        </div>
        {a.stuck_top.length ? (
          <div>
            <p className="mb-1.5 text-sm font-medium">Дольше всех стоят</p>
            <ul className="space-y-1.5 text-sm">
              {a.stuck_top.map((d) => (
                <li key={d.deal_id} className="min-w-0">
                  <Link href={`/deals/${d.deal_id}`} className="text-primary hover:underline">
                    №{d.bitrix_id} {d.title}
                  </Link>
                  <span className="text-muted-foreground">
                    {" "}
                    — {d.stage}, {formatDuration(d.in_stage_seconds, { work: d.unit !== "calendar_days" })} при сроке {d.rule}
                    {d.manager ? ` · ${d.manager}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {a.ai?.headline ? (
          <Link href="/ai" className="flex items-start gap-2 rounded-lg bg-muted/60 p-3 text-sm hover:bg-muted">
            <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
            <span>
              <span className="font-medium">Вывод ИИ: </span>
              {a.ai.headline} <span className="text-primary">Подробнее →</span>
            </span>
          </Link>
        ) : null}
      </CardContent>
    </Card>
  );
}

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
  const conv = kpis ? conversion(kpis.won_count, kpis.lost_count) : null;
  const prevConv = cmp ? conversion(cmp.won_count.previous, cmp.lost_count.previous) : null;
  const conversionDelta = conv !== null && prevConv !== null ? { previous: prevConv, delta: conv - prevConv, delta_pct: null } : null;

  const pipelineData = useMemo(
    () => ((charts?.deals_by_pipeline as PipelineCount[] | undefined) ?? []).slice().sort((a, b) => b.count - a.count),
    [charts],
  );
  const pipelineTotal = pipelineData.reduce((n, p) => n + p.count, 0);

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

  // The deals cursor, not "latest run of any kind": Avito syncs on its own schedule
  const lastSync =
    dash.data?.sync?.last_deals_sync?.at ||
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
            <FilterSelect
              id="dash-pipeline"
              value={pipelineId ?? ""}
              onChange={(e) => filters.setPipeline(e.target.value ? Number(e.target.value) : undefined)}
            >
              <option value="">Все воронки</option>
              {(pipelines.data ?? []).map((p) => (
                <option key={p.id} value={String(p.bitrix_id)}>
                  {p.name}
                </option>
              ))}
            </FilterSelect>
          </div>
          <div className="w-full space-y-1.5 sm:w-52">
            <Label htmlFor="dash-manager" className="block text-xs text-muted-foreground">
              Менеджер
            </Label>
            <FilterSelect
              id="dash-manager"
              value={managerId ?? ""}
              onChange={(e) => filters.setManager(e.target.value ? Number(e.target.value) : undefined)}
            >
              <option value="">Все менеджеры</option>
              {sortedManagers.map((m) => (
                <option key={m.id} value={m.id}>
                  {managerName(m)}
                </option>
              ))}
            </FilterSelect>
          </div>
          {filtered ? (
            <Button variant="ghost" size="sm" className="h-10" onClick={filters.reset}>
              Сбросить
            </Button>
          ) : null}
          {dash.isFetching && kpis ? <span className="h-10 text-sm leading-10 text-muted-foreground">Обновляем…</span> : null}
        </div>
      </div>

      <DataStatus system={system.data} lastSync={lastSync || null} computedAt={kpis?.computed_at} />

      {kpis?.data_quality?.note ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {kpis.data_quality.note}
        </p>
      ) : null}

      {dash.data?.attention ? (
        <AttentionBlock a={dash.data.attention} overdueActivities={kpis?.overdue_activities_unique} href={(p) => dealsHref(scope, p)} />
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
              title="Конверсия в успех"
              value={formatPercent(conversion(kpis.won_count, kpis.lost_count))}
              href={dealsHref(scope, { outcome: "won", closed_from: period.from, closed_to: period.to })}
              hint="выиграно ÷ (выиграно + проиграно) среди закрытых за период"
              delta={conversionDelta}
              formatPrevious={(v) => formatPercent(v)}
              freshness={kpis.computed_at}
            />
            <KpiCard
              title="Средний чек"
              value={kpis.won_count ? formatMoney(kpis.sum_won_opportunity / kpis.won_count) : "—"}
              href={dealsHref(scope, { outcome: "won", closed_from: period.from, closed_to: period.to, sort_by: "opportunity", sort_dir: "desc" })}
              hint="сумма выигранных ÷ число выигранных за период"
              freshness={kpis.computed_at}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            Сравнение — с предыдущим периодом такой же длины. «Активные» и «Сумма в работе» — на сейчас.
          </p>
        </div>
      ) : (
        <EmptyState title="Нет KPI" description="API не вернул метрики за период." />
      )}

      <div className="grid items-start gap-6 lg:grid-cols-2 [&>*]:min-w-0">
        <Card>
          <CardHeader>
            <CardTitle>Новые и успешно закрытые</CardTitle>
            <CardDescription>По дням, московское время</CardDescription>
          </CardHeader>
          <CardContent className="h-72">
            {!series.length || series.every((d) => d.new === 0 && d.won === 0) ? (
              <EmptyState title="Нет данных для графика" />
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={series} barGap={1} barCategoryGap="20%">
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                  <XAxis dataKey="date" tickFormatter={dayLabel} tick={{ fontSize: 11 }} minTickGap={16} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 12 }} width={28} />
                  <Tooltip labelFormatter={(v) => formatDate(String(v))} cursor={{ fill: "var(--muted)", opacity: 0.5 }} />
                  <Legend verticalAlign="top" height={28} iconType="square" />
                  <Bar dataKey="new" name="Новые" fill={NEW_COLOR} radius={[3, 3, 0, 0]} />
                  <Bar dataKey="won" name="Успешно закрыто" fill={WON_COLOR} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Активные сделки по воронкам</CardTitle>
            <CardDescription>Количество и сумма в работе</CardDescription>
          </CardHeader>
          <CardContent>
            {pipelineData.length === 0 ? (
              <EmptyState title="Нет активных сделок" />
            ) : (
              <ul className="space-y-5">
                {pipelineData.map((p) => (
                  <li key={p.category_id ?? p.name}>
                    <div className="flex flex-wrap items-baseline justify-between gap-x-3 text-sm">
                      <Link
                        href={dealsHref({ ...scope, pipelineId: p.category_id ?? undefined }, { closed: false })}
                        className="font-medium text-primary hover:underline"
                      >
                        {p.name}
                      </Link>
                      <span>
                        <strong className="font-semibold">{formatNumber(p.count)}</strong> сделок
                        {p.sum !== undefined ? <span className="text-muted-foreground"> · {formatMoney(p.sum)}</span> : null}
                      </span>
                    </div>
                    <div className="mt-1.5 h-2 rounded-full bg-muted">
                      <div className="h-2 rounded-full bg-primary" style={{ width: `${(p.count / Math.max(1, pipelineTotal)) * 100}%` }} />
                    </div>
                  </li>
                ))}
              </ul>
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

      <div className="grid gap-6 xl:grid-cols-2 [&>*]:min-w-0">
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
                        {d.stalled ? <Badge variant="destructive">Застой</Badge> : null}
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
            <CardDescription>Что изменилось в сделках — по данным синхронизации с Bitrix</CardDescription>
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

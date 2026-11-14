"use client";

import { ChevronDown, ChevronRight, Sparkles } from "lucide-react";
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
import { DeltaLine, KpiCard } from "@/components/common/kpi-card";
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
import { useDashboard, useManagers, usePipelines, useSystem, useTargetsProgress } from "@/hooks/queries";
import { formatDate, formatDateTime, formatDuration, formatMoney, formatNumber, formatPercent, managerName } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DashboardResponse, DealChangeEvent, NamedCount, PipelineCount, SystemStatus } from "@/types/api";

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

const cellGrid = "grid gap-px overflow-hidden rounded-lg border border-border bg-border";

/** White cell, coloured dot: red is kept for what is actually wrong. */
function AttentionStat({ label, value, href, note, tone }: { label: string; value: string; href: string; note?: string; tone: Tone }) {
  return (
    <Link href={href} className="group flex flex-col gap-1 bg-card p-4 transition-colors hover:bg-muted/50">
      <span className="flex items-center gap-2 text-sm text-muted-foreground">
        <span
          aria-hidden
          className={cn("h-2 w-2 shrink-0 rounded-full", tone === "bad" && "bg-red-600", tone === "warn" && "bg-amber-500", tone === "ok" && "bg-emerald-600")}
        />
        <span className="min-w-0 flex-1">{label}</span>
        <ChevronRight className="h-4 w-4 shrink-0 opacity-40 transition-transform group-hover:translate-x-0.5 group-hover:opacity-100" aria-hidden />
      </span>
      <span className={cn("font-serif text-4xl font-semibold tabular-nums tracking-tight", tone === "bad" && "text-red-700")}>{value}</span>
      {note ? <span className="text-[13px] text-muted-foreground">{note}</span> : null}
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
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4">
        <h2 className="font-serif text-xl font-semibold tracking-tight">Требует внимания</h2>
        <p className="text-[13px] text-muted-foreground">Состояние на сейчас</p>
      </div>
      <div className={cn(cellGrid, "grid-cols-2 shadow-sm", a.avito ? "xl:grid-cols-4" : "xl:grid-cols-3")}>
        <AttentionStat
          label="Сделки с просрочкой"
          value={formatNumber(a.overdue_deals)}
          href={href({ overdue: true })}
          note={overdueActivities ? `просроченных дел: ${formatNumber(overdueActivities)}` : undefined}
          tone={tone(a.overdue_deals)}
        />
        <AttentionStat label="Зависшие сделки" value={formatNumber(a.stuck)} href="/stalled" note="дольше срока стадии" tone={tone(a.stuck)} />
        <AttentionStat
          label="Без следующего дела"
          value={formatNumber(a.no_next_activity)}
          href={href({ closed: false, has_future_activity: false, sort_by: "opportunity", sort_dir: "desc" })}
          note="по регламенту дело обязательно"
          tone={tone(a.no_next_activity, 5)}
        />
        {a.avito ? (
          <AttentionStat
            label="Avito без ответа"
            value={formatNumber(a.avito.unanswered)}
            href="/avito"
            note={a.avito.late ? `из них дольше нормы: ${a.avito.late}` : "все в пределах нормы"}
            tone={a.avito.late ? "bad" : a.avito.unanswered ? "warn" : "ok"}
          />
        ) : null}
      </div>
      {a.stuck_top.length ? (
        <Card>
          <CardContent className="p-0">
            <p className="px-4 pt-3 text-sm font-medium">Дольше всех стоят на этапе</p>
            <ul className="divide-y divide-border">
              {a.stuck_top.map((d) => (
                <li key={d.deal_id} className="flex flex-col gap-x-4 gap-y-0.5 px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <Link href={`/deals/${d.deal_id}`} className="block truncate text-sm font-medium text-primary hover:underline" title={d.title}>
                      {d.title}
                    </Link>
                    <p className="truncate text-[13px] text-muted-foreground">{[d.stage, d.manager].filter(Boolean).join(" · ")}</p>
                  </div>
                  <p className="shrink-0 text-sm sm:text-right">
                    <span className="font-semibold text-red-700">{formatDuration(d.in_stage_seconds, { work: d.unit !== "calendar_days" })}</span>
                    <span className="text-[13px] text-muted-foreground"> при сроке {d.rule}</span>
                  </p>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
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
    </section>
  );
}

/** Secondary number: smaller than a KPI card, same click-through. */
function MiniStat({ label, value, href, children }: { label: string; value: string; href: string; children?: React.ReactNode }) {
  return (
    <Link href={href} className="block bg-card p-4 transition-colors hover:bg-muted/50">
      <p className="text-[13px] text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-xl font-semibold tabular-nums">{value}</p>
      {children}
    </Link>
  );
}

type ChangeGroup = { key: string; dealId: number; title: string; at: string; lines: string[] };

/** One entry per deal: the sync writes a row per field, so a single edit used to fill the list. */
function groupChanges(changes: DealChangeEvent[], limit: number, pipelineNames: Map<string, string>): ChangeGroup[] {
  const groups: ChangeGroup[] = [];
  for (const c of changes) {
    // «Закрыта: нет → да» always comes with the stage change that says the same
    if (c.field_name === "closed") continue;
    // The log keeps the pipeline as a Bitrix id
    const named = (v: string | null | undefined) => (c.field_name === "category_id" && v ? (pipelineNames.get(v) ?? v) : v);
    const from = named(c.old_label ?? c.old_value);
    const to = named(c.new_label ?? c.new_value);
    let line: string;
    if (c.field_name === "opportunity") line = `Сумма: ${formatMoney(from)} → ${formatMoney(to)}`;
    else if (c.field_name === "title") line = from ? `Переименована, было: ${from}` : "Переименована";
    else line = `${c.field_label ?? c.field_name}: ${from ?? "—"} → ${to ?? "—"}`;
    const last = groups[groups.length - 1];
    if (last && last.dealId === c.deal_id) {
      if (!last.lines.includes(line)) last.lines.push(line);
      continue;
    }
    if (groups.length === limit) break;
    groups.push({ key: `${c.deal_id}-${c.observed_at}`, dealId: c.deal_id, title: c.deal_title || `Сделка #${c.deal_id}`, at: c.observed_at, lines: [line] });
  }
  return groups;
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
  // People who left the company stay in old deals but do not belong in the filter
  const sortedManagers = (managers.data ?? [])
    .filter((m) => m.is_active !== false || m.id === managerId)
    .sort((a, b) => managerName(a).localeCompare(managerName(b)));
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
  const managerMax = Math.max(1, ...managerData.map((m) => m.count));

  const changeGroups = useMemo(
    () => groupChanges(dash.data?.recent_changes ?? [], 6, new Map((pipelines.data ?? []).map((p) => [String(p.bitrix_id), p.name]))),
    [dash.data?.recent_changes, pipelines.data],
  );
  const series = charts?.series_daily ?? kpis?.series_daily ?? [];
  const problemDeals = (dash.data?.problem_deals ?? []).slice(0, 8);

  if (dash.isLoading && !kpis) return <PageLoading rows={6} />;
  if (dash.isError) return <ErrorState message="Не удалось загрузить дашборд." onRetry={() => void dash.refetch()} />;

  // The deals cursor, not "latest run of any kind": Avito syncs on its own schedule
  const lastSync =
    dash.data?.sync?.last_deals_sync?.at ||
    (typeof system.data?.last_deals_sync === "object" && system.data?.last_deals_sync?.at) ||
    null;
  const wonHref = dealsHref(scope, { outcome: "won", closed_from: period.from, closed_to: period.to });

  return (
    <div className="mx-auto max-w-7xl space-y-10">
      <div className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
          <h1 className="font-serif text-3xl font-semibold tracking-tight">Дашборд</h1>
          <DataStatus system={system.data?.sync_stalled || !system.data?.bitrix_configured ? undefined : system.data} lastSync={lastSync || null} computedAt={kpis?.computed_at} />
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <PeriodPicker value={period} onChange={filters.setPeriod} />
          <div className="w-full space-y-1.5 sm:w-48">
            <Label htmlFor="dash-pipeline" className="block text-[13px] text-muted-foreground">
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
            <Label htmlFor="dash-manager" className="block text-[13px] text-muted-foreground">
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

      {/* Warnings take the full width; the ordinary «data as of» line sits next to the title */}
      {system.data?.sync_stalled || (system.data && !system.data.bitrix_configured) ? (
        <DataStatus system={system.data} lastSync={lastSync || null} computedAt={kpis?.computed_at} />
      ) : null}

      {kpis?.data_quality?.note ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {kpis.data_quality.note}
        </p>
      ) : null}

      {dash.data?.attention ? (
        <AttentionBlock a={dash.data.attention} overdueActivities={kpis?.overdue_activities_unique} href={(p) => dealsHref(scope, p)} />
      ) : null}

      {kpis ? (
        <section className="space-y-4">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4">
            <h2 className="font-serif text-xl font-semibold tracking-tight">Продажи за период</h2>
            <p className="text-[13px] text-muted-foreground">
              {formatDate(period.from)} — {formatDate(period.to)}
              {dash.data?.comparison ? (
                <>
                  {" "}
                  · в сравнении с {formatDate(dash.data.comparison.period_start)} — {formatDate(dash.data.comparison.period_end)}
                </>
              ) : null}
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              title="Сумма выигранных"
              value={formatMoney(kpis.sum_won_opportunity)}
              href={dealsHref(scope, { outcome: "won", closed_from: period.from, closed_to: period.to, sort_by: "opportunity", sort_dir: "desc" })}
              delta={cmp?.sum_won_opportunity}
              formatPrevious={(v) => formatMoney(v)}
              source={kpis.definitions?.sum_won_opportunity?.source}
              formula={kpis.definitions?.sum_won_opportunity?.formula}
              freshness={kpis.computed_at}
            />
            <KpiCard
              title="Успешно закрыто"
              value={formatNumber(kpis.won_count)}
              href={wonHref}
              delta={cmp?.won_count}
              source={kpis.definitions?.won_count?.source}
              formula={kpis.definitions?.won_count?.formula}
              freshness={kpis.computed_at}
            />
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
              title="Конверсия в успех"
              value={formatPercent(conv)}
              href={wonHref}
              hint="выиграно ÷ (выиграно + проиграно) среди закрытых за период"
              delta={conversionDelta}
              formatPrevious={(v) => formatPercent(v)}
              freshness={kpis.computed_at}
            />
          </div>

          <div className="grid items-start gap-4 lg:grid-cols-3 [&>*]:min-w-0">
            <Card className="lg:col-span-2">
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
                      <XAxis dataKey="date" tickFormatter={dayLabel} tick={{ fontSize: 12 }} minTickGap={16} />
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

            <div className="space-y-4">
              <div className={cn(cellGrid, "grid-cols-2 shadow-sm lg:grid-cols-1")}>
                <MiniStat label="Проиграно" value={formatNumber(kpis.lost_count)} href={dealsHref(scope, { outcome: "lost", closed_from: period.from, closed_to: period.to })}>
                  {cmp?.lost_count ? <DeltaLine delta={cmp.lost_count} higherIsBetter={false} /> : null}
                </MiniStat>
                <MiniStat
                  label="Средний чек"
                  value={kpis.won_count ? formatMoney(kpis.sum_won_opportunity / kpis.won_count) : "—"}
                  href={dealsHref(scope, { outcome: "won", closed_from: period.from, closed_to: period.to, sort_by: "opportunity", sort_dir: "desc" })}
                />
              </div>
              {shownPlan ? (
                <Link href="/plan" className="block">
                  <PlanProgressCard p={shownPlan} compact />
                </Link>
              ) : null}
            </div>
          </div>
        </section>
      ) : (
        <EmptyState title="Нет KPI" description="API не вернул метрики за период." />
      )}

      <section className="space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 className="font-serif text-xl font-semibold tracking-tight">В работе сейчас</h2>
          {kpis ? (
            <p className="text-sm text-muted-foreground">
              <Link href={dealsHref(scope, { closed: false })} className="hover:underline">
                <strong className="font-semibold text-foreground">{formatNumber(kpis.active_deals_count)}</strong> активных сделок
              </Link>{" "}
              ·{" "}
              <Link href={dealsHref(scope, { closed: false, sort_by: "opportunity", sort_dir: "desc" })} className="hover:underline">
                <strong className="font-semibold text-foreground">{formatMoney(kpis.sum_active_opportunity)}</strong> в работе
              </Link>
            </p>
          ) : null}
        </div>

        <div className="grid items-start gap-4 lg:grid-cols-2 [&>*]:min-w-0">
          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>По воронкам</CardTitle>
              </CardHeader>
              <CardContent>
                {pipelineData.length === 0 ? (
                  <EmptyState title="Нет активных сделок" />
                ) : (
                  <ul className="space-y-4">
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
                            <strong className="font-semibold">{formatNumber(p.count)}</strong>
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

            <Card>
              <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0">
                <div className="space-y-1.5">
                  <CardTitle>По менеджерам</CardTitle>
                  <CardDescription>Активные сделки, у кого больше всего</CardDescription>
                </div>
                <Link href="/managers" className="shrink-0 text-sm text-primary hover:underline">
                  Все →
                </Link>
              </CardHeader>
              <CardContent>
                {managerData.length === 0 ? (
                  <EmptyState title="Нет данных по менеджерам" />
                ) : (
                  <ul className="space-y-2.5">
                    {managerData.map((m) => (
                      <li key={m.manager_id ?? m.name} className="grid grid-cols-[minmax(0,11rem)_1fr_2.5rem] items-center gap-3 text-sm">
                        {m.manager_id ? (
                          <Link href={`/managers/${m.manager_id}`} className="truncate hover:underline" title={m.name}>
                            {m.name}
                          </Link>
                        ) : (
                          <span className="truncate text-muted-foreground">{m.name}</span>
                        )}
                        <div className="h-2 rounded-full bg-muted">
                          <div className="h-2 rounded-full bg-accent" style={{ width: `${(m.count / managerMax) * 100}%` }} />
                        </div>
                        <span className="text-right font-semibold tabular-nums">{formatNumber(m.count)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0">
              <div className="space-y-1.5">
                <CardTitle>Крупные сделки без следующего дела</CardTitle>
                <CardDescription>Здесь деньги, о которых могут забыть</CardDescription>
              </div>
              <Link
                href={dealsHref(scope, { closed: false, has_future_activity: false, sort_by: "opportunity", sort_dir: "desc" })}
                className="shrink-0 text-sm text-primary hover:underline"
              >
                Все →
              </Link>
            </CardHeader>
            <CardContent className="p-0 pb-2">
              {problemDeals.length === 0 ? (
                <div className="px-6 pb-4">
                  <EmptyState title="Таких сделок нет" />
                </div>
              ) : (
                <ul className="divide-y divide-border">
                  {problemDeals.map((d) => (
                    <li key={d.deal_id} className="flex items-start justify-between gap-4 px-6 py-3">
                      <div className="min-w-0">
                        <Link href={`/deals/${d.deal_id}`} className="block truncate text-sm font-medium text-primary hover:underline" title={d.title}>
                          {d.title}
                        </Link>
                        <p className="truncate text-[13px] text-muted-foreground">{[d.stage, d.manager].filter(Boolean).join(" · ")}</p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="whitespace-nowrap text-sm font-semibold tabular-nums">{formatMoney(d.opportunity)}</p>
                        {d.stalled ? <Badge variant="destructive">Застой</Badge> : null}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4">
          <h2 className="font-serif text-xl font-semibold tracking-tight">Последние изменения</h2>
          <p className="text-[13px] text-muted-foreground">Что менеджеры меняли в сделках</p>
        </div>
        {changeGroups.length === 0 ? (
          <EmptyState title="Изменений пока нет" />
        ) : (
          <Card>
            <CardContent className="p-0">
              <ul className="grid divide-y divide-border lg:grid-cols-2 lg:divide-y-0">
                {changeGroups.map((g) => (
                  <li key={g.key} className="min-w-0 px-6 py-3 lg:border-b lg:border-border">
                    <div className="flex items-baseline justify-between gap-3">
                      <Link href={`/deals/${g.dealId}`} className="truncate text-sm font-medium text-primary hover:underline" title={g.title}>
                        {g.title}
                      </Link>
                      <span className="shrink-0 text-[13px] text-muted-foreground">{formatDateTime(g.at)}</span>
                    </div>
                    {g.lines.map((line) => (
                      <p key={line} className="text-sm text-muted-foreground">
                        {line}
                      </p>
                    ))}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}
      </section>
    </div>
  );
}

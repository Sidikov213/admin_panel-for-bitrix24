"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { DataFreshness } from "@/components/common/data-freshness";
import { DeltaBadge } from "@/components/common/delta-badge";
import { ErrorState, PageLoading } from "@/components/common/page-states";
import { PeriodPicker, defaultPeriod, type PeriodValue } from "@/components/common/period-picker";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useManager, useSystem } from "@/hooks/queries";
import { api } from "@/lib/api";
import { formatMoney, formatNumber } from "@/lib/format";
import type { MetricDelta } from "@/types/api";

function ManagerDetailInner() {
  const params = useParams<{ id: string }>();
  const search = useSearchParams();
  const id = Number(params.id);
  const [period, setPeriod] = useState<PeriodValue>(defaultPeriod);
  const metric = search.get("metric");
  const q = useManager(id, {
    preset: period.preset === "custom" ? undefined : period.preset,
    period_start: period.from,
    period_end: period.to,
  });
  const system = useSystem();
  const [drill, setDrill] = useState<Array<Record<string, unknown>>>([]);

  useEffect(() => {
    if (!metric || !id) return;
    let cancelled = false;
    void api
      .managerDeals(id, metric, {
        preset: period.preset === "custom" ? undefined : period.preset,
        period_start: period.from,
        period_end: period.to,
      })
      .then((r) => {
        if (!cancelled) setDrill(r.items);
      })
      .catch(() => {
        if (!cancelled) setDrill([]);
      });
    return () => {
      cancelled = true;
    };
  }, [id, metric, period]);

  const drillRows = !metric || !id ? [] : drill;

  if (q.isLoading) return <PageLoading rows={6} />;
  if (q.isError || !q.data)
    return <ErrorState message="Не удалось загрузить менеджера." onRetry={() => void q.refetch()} />;

  const { manager, kpis, comparison, plan_fact, problem_deals, deals } = q.data;
  const cmp = comparison?.metrics;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <Link href="/managers" className="text-[12px] text-muted-foreground hover:text-foreground">
            ← Менеджеры
          </Link>
          <h1 className="page-title mt-1 text-[1.5rem]">
            {manager.name} {manager.last_name}
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <PeriodPicker value={period} onChange={setPeriod} compact />
          <DataFreshness freshness={system.data?.freshness} compact />
        </div>
      </div>

      <section className="grid grid-cols-2 gap-x-6 gap-y-4 border-y border-border py-4 sm:grid-cols-4 lg:grid-cols-8">
        <Strip label="Активные" value={formatNumber(kpis.active_deals_count)} delta={cmp?.active_deals_count} />
        <Strip label="Новые" value={formatNumber(kpis.new_deals_count)} delta={cmp?.new_deals_count} />
        <Strip label="Won" value={formatNumber(kpis.won_count)} delta={cmp?.won_count} />
        <Strip label="Lost" value={formatNumber(kpis.lost_count)} delta={cmp?.lost_count} />
        <Strip label="Сумма акт." value={formatMoney(kpis.sum_active_opportunity)} />
        <Strip label="Сумма won" value={formatMoney(kpis.sum_won_opportunity)} />
        <Strip label="Просрочки" value={formatNumber(kpis.overdue_activities_unique)} />
        <Strip label="Без дела" value={formatNumber(kpis.deals_without_future_activity_count)} />
      </section>

      {plan_fact ? (
        <section className="flex flex-wrap gap-x-8 gap-y-2 text-[13px]">
          <span>
            <span className="text-muted-foreground">План </span>
            {plan_fact.plan_set ? formatMoney(plan_fact.plan) : "не задан"}
          </span>
          <span>
            <span className="text-muted-foreground">Факт </span>
            {formatMoney(plan_fact.fact)}
          </span>
          <span>
            <span className="text-muted-foreground">% </span>
            {plan_fact.percent ?? "—"}
          </span>
        </section>
      ) : null}

      {metric ? (
        <section className="panel overflow-hidden">
          <div className="border-b border-border px-4 py-2.5">
            <h2 className="section-title">Drill-down: {metric}</h2>
          </div>
          <Table className="data-table">
            <TableHeader>
              <TableRow>
                <TableHead className="pl-4">Сделка</TableHead>
                <TableHead>Этап</TableHead>
                <TableHead className="pr-4 text-right">Сумма</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {drillRows.map((d) => (
                <TableRow key={String(d.id)} className="interactive-row">
                  <TableCell className="pl-4">
                    <Link href={`/deals/${d.id}`} className="font-medium hover:text-primary">
                      {String(d.title)}
                    </Link>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{String(d.stage_name ?? "—")}</TableCell>
                  <TableCell className="pr-4 text-right tabular-nums">{formatMoney(d.opportunity as number)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      ) : null}

      <section className="panel overflow-hidden">
        <div className="border-b border-border px-4 py-2.5">
          <h2 className="section-title">Требует внимания</h2>
        </div>
        <Table className="data-table">
          <TableHeader>
            <TableRow>
              <TableHead className="pl-4">Сделка</TableHead>
              <TableHead>Факт</TableHead>
              <TableHead>Этап</TableHead>
              <TableHead className="pr-4 text-right">Сумма</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(problem_deals ?? []).length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="py-6 text-center text-muted-foreground">
                  Нет проблемных сделок
                </TableCell>
              </TableRow>
            ) : (
              (problem_deals ?? []).map((d) => (
                <TableRow key={d.id} className="interactive-row">
                  <TableCell className="pl-4">
                    <Link href={`/deals/${d.id}`} className="font-medium hover:text-primary">
                      {d.title}
                    </Link>
                  </TableCell>
                  <TableCell className="text-[13px]">{d.fact}</TableCell>
                  <TableCell className="text-muted-foreground">{d.stage_name ?? "—"}</TableCell>
                  <TableCell className="pr-4 text-right tabular-nums">{formatMoney(d.opportunity)}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </section>

      <section className="panel overflow-hidden">
        <div className="border-b border-border px-4 py-2.5">
          <h2 className="section-title">Сделки</h2>
        </div>
        <Table className="data-table">
          <TableHeader>
            <TableRow>
              <TableHead className="pl-4">Сделка</TableHead>
              <TableHead>Этап</TableHead>
              <TableHead>Будущее дело</TableHead>
              <TableHead className="pr-4 text-right">Сумма</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {deals.map((d) => (
              <TableRow key={d.id} className="interactive-row">
                <TableCell className="pl-4">
                  <Link href={`/deals/${d.id}`} className="font-medium hover:text-primary">
                    {d.title}
                  </Link>
                </TableCell>
                <TableCell className="text-muted-foreground">{d.stage_name ?? "—"}</TableCell>
                <TableCell>{d.has_future_activity ? "есть" : "нет"}</TableCell>
                <TableCell className="pr-4 text-right tabular-nums">{formatMoney(d.opportunity)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>
    </div>
  );
}

function Strip({ label, value, delta }: { label: string; value: string; delta?: MetricDelta | null }) {
  return (
    <div className="min-w-0">
      <p className="meta truncate">{label}</p>
      <p className="mt-0.5 text-[1.125rem] font-semibold tabular-nums tracking-tight">{value}</p>
      {delta ? <DeltaBadge delta={delta} /> : null}
    </div>
  );
}

export default function ManagerDetailPage() {
  return (
    <Suspense fallback={<PageLoading rows={6} />}>
      <ManagerDetailInner />
    </Suspense>
  );
}

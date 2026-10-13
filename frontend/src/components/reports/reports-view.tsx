"use client";

import { useState } from "react";
import { DataFreshness } from "@/components/common/data-freshness";
import { DeltaBadge } from "@/components/common/delta-badge";
import { ErrorState, PageLoading } from "@/components/common/page-states";
import { PeriodPicker, defaultPeriod, type PeriodValue } from "@/components/common/period-picker";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useReports } from "@/hooks/queries";
import { formatMoney, formatNumber } from "@/lib/format";
import { getDynamicsKeyLabel } from "@/lib/ui-labels";
import type { MetricDelta, PlanFact } from "@/types/api";

export function ReportsView() {
  const [period, setPeriod] = useState<PeriodValue>({ ...defaultPeriod(), preset: "current_week" });
  const q = useReports({
    preset: period.preset === "custom" ? undefined : period.preset,
    period_start: period.from,
    period_end: period.to,
  });

  if (q.isLoading) return <PageLoading rows={6} />;
  if (q.isError) return <ErrorState message="Не удалось загрузить отчёт." onRetry={() => void q.refetch()} />;
  const data = q.data;
  if (!data) return null;

  const overview = data.overview as Record<string, unknown> | undefined;
  const planFact = overview?.plan_fact as PlanFact | undefined;
  const problems = data.problems as Record<string, number> | undefined;
  const managers = (data.managers as Array<Record<string, unknown>>) || [];
  const dynamics = data.dynamics as Record<string, MetricDelta> | undefined;
  const reg = data.regulation_violations as
    | {
        configured?: boolean;
        enabled?: boolean;
        message?: string;
        open?: number;
        new_during_period?: number;
        resolved?: number;
        by_type?: Array<{ type: string; count: number }>;
        by_manager?: Array<{ manager_name: string; count: number }>;
      }
    | undefined;

  return (
    <div className="section-stack">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="meta">Недельный управленческий отчёт</p>
          <h1 className="mt-1 text-[1.25rem] font-semibold tracking-tight">{data.title || "Отчёт"}</h1>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <PeriodPicker value={period} onChange={setPeriod} compact />
          <DataFreshness freshness={data.freshness} compact />
        </div>
      </div>

      <section className="panel">
        <div className="panel-header">
          <h2 className="section-title">Общая картина</h2>
          <span className="meta">сводка за период</span>
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-5 px-5 py-5 sm:grid-cols-4">
          <Metric
            label="План"
            value={planFact?.plan_set ? formatMoney(planFact.plan) : "не задан"}
          />
          <Metric label="Факт (выиграно)" value={formatMoney((overview?.sum_won as number) ?? planFact?.fact)} />
          <Metric
            label="Новые / Выиграно / Проиграно"
            value={`${formatNumber(overview?.new_deals as number)} / ${formatNumber(overview?.won as number)} / ${formatNumber(overview?.lost as number)}`}
          />
          <div>
            <p className="meta">Активная воронка</p>
            <p className="mt-1.5 text-[1.375rem] font-semibold tabular-nums tracking-tight">
              {formatNumber(overview?.active_pipeline_count as number)}
            </p>
            <p className="mt-0.5 text-[13px] text-muted-foreground">
              {formatMoney(overview?.active_pipeline_amount as number)}
            </p>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2 className="section-title">Проблемы</h2>
          <span className="meta">сигналы контроля</span>
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-5 px-5 py-5 sm:grid-cols-4">
          <Metric label="Просроченные" value={formatNumber(problems?.overdue)} />
          <Metric label="Без следующего дела" value={formatNumber(problems?.no_future_activity)} />
          <Metric label="Требуют внимания" value={formatNumber(problems?.deals_requiring_attention)} />
          <Metric label="Сумма внимания" value={formatMoney(problems?.money_requiring_attention)} />
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2 className="section-title">Нарушения регламента</h2>
        </div>
        <div className="px-5 py-5">
          {!reg || reg.configured === false ? (
            <p className="text-[13px] text-muted-foreground">{reg?.message || "Регламент не настроен"}</p>
          ) : reg.enabled === false ? (
            <p className="text-[13px] text-muted-foreground">{reg.message || "Правила выключены"}</p>
          ) : (
            <div className="space-y-5">
              <div className="grid grid-cols-3 gap-6">
                <Metric label="Открыто" value={formatNumber(reg.open)} />
                <Metric label="Новые за период" value={formatNumber(reg.new_during_period)} />
                <Metric label="Устранено" value={formatNumber(reg.resolved)} />
              </div>
              {(reg.by_type?.length || 0) > 0 ? (
                <ul className="divide-y divide-border rounded-md border border-border">
                  {reg.by_type!.map((t) => (
                    <li key={t.type} className="flex justify-between gap-3 px-3.5 py-2.5 text-[13px]">
                      <span>{t.type}</span>
                      <span className="tabular-nums text-muted-foreground">{t.count}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          )}
        </div>
      </section>

      <section className="panel overflow-hidden">
        <div className="panel-header">
          <h2 className="section-title">Менеджеры</h2>
          <span className="meta">{managers.length} чел.</span>
        </div>
        <div className="overflow-x-auto">
          <Table className="data-table">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-5">Менеджер</TableHead>
                <TableHead className="text-right">Активные</TableHead>
                <TableHead className="text-right">Новые</TableHead>
                <TableHead className="text-right">Выиграно</TableHead>
                <TableHead className="text-right">Сумма выигранных</TableHead>
                <TableHead className="text-right">Просроченные</TableHead>
                <TableHead className="pr-5 text-right">Без дела</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {managers.map((m) => (
                <TableRow key={String(m.id)} className="interactive-row">
                  <TableCell className="pl-5 font-medium">{String(m.name)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatNumber(m.active_deals as number)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatNumber(m.new_deals as number)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatNumber(m.won as number)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatMoney(m.sum_won as number)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatNumber(m.overdue as number)}</TableCell>
                  <TableCell className="pr-5 text-right tabular-nums">{formatNumber(m.no_future as number)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>

      {dynamics ? (
        <section className="panel">
          <div className="panel-header">
            <h2 className="section-title">Динамика vs предыдущий период</h2>
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-5 px-5 py-5 sm:grid-cols-3 lg:grid-cols-6">
            {Object.entries(dynamics).map(([key, d]) => (
              <div key={key}>
                <p className="meta">{getDynamicsKeyLabel(key)}</p>
                <p className="mt-1.5 text-[1.25rem] font-semibold tabular-nums tracking-tight">{d.current}</p>
                <div className="mt-0.5">
                  <DeltaBadge delta={d} />
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="meta">{label}</p>
      <p className="mt-1.5 text-[1.375rem] font-semibold tabular-nums tracking-tight">{value}</p>
    </div>
  );
}

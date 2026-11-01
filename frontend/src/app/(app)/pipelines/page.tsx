"use client";

import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  CATEGORY_AXIS_WIDTH,
  CATEGORY_LABEL_WIDTH,
  CategoryAxisTick,
  CategoryBarTooltip,
  categoryChartHeight,
} from "@/components/charts/category-axis-tick";
import { DataFreshness } from "@/components/common/data-freshness";
import { ErrorState, PageLoading } from "@/components/common/page-states";
import { PeriodPicker, defaultPeriod, type PeriodValue } from "@/components/common/period-picker";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usePipelines, useSystem } from "@/hooks/queries";
import { formatMoney, formatNumber } from "@/lib/format";

export default function PipelinesPage() {
  const [period, setPeriod] = useState<PeriodValue>(defaultPeriod);
  const q = usePipelines({
    preset: period.preset === "custom" ? undefined : period.preset,
    period_start: period.from,
    period_end: period.to,
  });
  const system = useSystem();

  if (q.isLoading) return <PageLoading rows={6} />;
  if (q.isError) return <ErrorState message="Не удалось загрузить воронки." onRetry={() => void q.refetch()} />;

  const pipes = !Array.isArray(q.data) && q.data?.pipelines ? q.data.pipelines : [];

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[13px] text-muted-foreground">
          Текущее распределение ≠ историческая конверсия
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <PeriodPicker value={period} onChange={setPeriod} compact />
          <DataFreshness freshness={system.data?.freshness} compact />
        </div>
      </div>

      {!Array.isArray(q.data) && q.data?.distinction ? (
        <p className="text-sm text-muted-foreground">
          <Badge variant="outline" className="mr-2">
            current distribution
          </Badge>
          {q.data.distinction.current_distribution}
          {" · "}
          <Badge variant="outline" className="mr-2">
            historical conversion
          </Badge>
          {q.data.distinction.historical_conversion}
        </p>
      ) : null}

      <div className="space-y-6">
        {pipes.map((p) => (
          <section key={p.id} className="panel">
            <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border px-4 py-3">
              <h2 className="section-title">{p.name}</h2>
              <p className="text-[13px] text-muted-foreground">
                {formatNumber(p.current_distribution.active_deals)} акт. ·{" "}
                {formatMoney(p.current_distribution.active_amount)} ·{" "}
                {p.current_distribution.share_of_all_active}%
              </p>
            </div>
            <div className="grid gap-4 p-4 lg:grid-cols-2">
              <div className="min-w-0 overflow-hidden" style={{ height: categoryChartHeight(p.funnel.length) }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={p.funnel} layout="vertical" margin={{ left: 8, right: 12, top: 8, bottom: 4 }} barCategoryGap={10}>
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
                    <Bar dataKey="value" name="Сделки" fill="var(--primary)" radius={[0, 3, 3, 0]} barSize={16} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="space-y-3">
                <Table className="data-table">
                  <TableHeader>
                    <TableRow>
                      <TableHead>Этап</TableHead>
                      <TableHead className="text-right">Сделок</TableHead>
                      <TableHead className="text-right">Сумма</TableHead>
                      <TableHead className="text-right">Доля</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {p.current_distribution.stages.map((s) => (
                      <TableRow key={s.id} className="interactive-row">
                        <TableCell>{s.name}</TableCell>
                        <TableCell className="text-right tabular-nums">{s.deals_count ?? 0}</TableCell>
                        <TableCell className="text-right tabular-nums">{formatMoney(s.amount)}</TableCell>
                        <TableCell className="text-right tabular-nums">{s.share_of_active_pipeline ?? 0}%</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <p className="text-[13px] text-muted-foreground">
                  Исходы: новые {p.period_outcomes.new_deals} · выиграно {p.period_outcomes.won} · проиграно{" "}
                  {p.period_outcomes.lost} · сумма выигр. {formatMoney(p.period_outcomes.sum_won)} · смены этапов{" "}
                  {p.period_outcomes.observed_stage_changes}
                </p>
              </div>
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

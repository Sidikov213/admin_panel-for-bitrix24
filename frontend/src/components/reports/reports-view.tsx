"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { PeriodPicker, defaultPeriod, type PeriodValue } from "@/components/common/period-picker";
import { PLAN_STATUS } from "@/components/plan/plan-progress-card";
import { ReportArchive } from "@/components/reports/report-archive";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useReports, useTargetsProgress } from "@/hooks/queries";
import { formatDate, formatMoney, formatNumber, formatPercent } from "@/lib/format";

export function ReportsView() {
  const [period, setPeriod] = useState<PeriodValue>(defaultPeriod);
  const reports = useReports(period.from, period.to);
  const targets = useTargetsProgress(false);

  const report = reports.data?.report;

  // Fact is computed per target over the target's own period and owner (not the report period)
  const planRows = useMemo(
    () => (targets.data?.items ?? []).filter((row) => row.period_start <= period.to && row.period_end >= period.from),
    [targets.data, period.from, period.to],
  );

  if (reports.isLoading) return <PageLoading rows={4} />;
  if (reports.isError) {
    return <ErrorState message="Не удалось загрузить отчёт." onRetry={() => void reports.refetch()} />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="font-serif text-3xl font-semibold">Отчёты</h1>
          <p className="text-sm text-muted-foreground">Периодные KPI и план/факт по целям продаж</p>
        </div>
        <PeriodPicker value={period} onChange={setPeriod} />
      </div>

      <ReportArchive />

      {!report ? (
        <EmptyState title="Нет данных отчёта" />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Новые", formatNumber(report.new_deals_count)],
            ["Выиграно", formatNumber(report.won_count)],
            ["Сумма выигранных", formatMoney(report.sum_won_opportunity)],
            ["Активные", formatNumber(report.active_deals_count)],
          ].map(([label, value]) => (
            <Card key={label}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="font-serif text-2xl font-semibold">{value}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle>План / факт</CardTitle>
          <Link href="/plan" className="text-sm text-primary hover:underline">
            Все цели →
          </Link>
        </CardHeader>
        <CardContent>
          {targets.isLoading ? (
            <PageLoading rows={1} />
          ) : !planRows.length ? (
            <p className="text-sm text-muted-foreground">План на этот период не задан.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Период цели</TableHead>
                  <TableHead>Для кого</TableHead>
                  <TableHead>План</TableHead>
                  <TableHead>Факт (выиграно)</TableHead>
                  <TableHead>Выполнение</TableHead>
                  <TableHead>Статус</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {planRows.map((row) => (
                  <TableRow key={row.target_id}>
                    <TableCell>
                      {formatDate(row.period_start)} — {formatDate(row.period_end)}
                    </TableCell>
                    <TableCell>{row.manager_id === null ? "Весь отдел" : (row.manager_name ?? `#${row.manager_id}`)}</TableCell>
                    <TableCell>{formatMoney(row.plan, row.currency)}</TableCell>
                    <TableCell>{formatMoney(row.fact, row.currency)}</TableCell>
                    <TableCell>{formatPercent(row.percent)}</TableCell>
                    <TableCell>
                      <Badge variant={PLAN_STATUS[row.status].variant}>{PLAN_STATUS[row.status].label}</Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

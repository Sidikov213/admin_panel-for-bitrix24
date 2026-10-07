"use client";

import { useMemo, useState } from "react";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { PeriodPicker, defaultPeriod, type PeriodValue } from "@/components/common/period-picker";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useReports, useTargets } from "@/hooks/queries";
import { formatDate, formatMoney, formatNumber } from "@/lib/format";

export function ReportsView() {
  const [period, setPeriod] = useState<PeriodValue>(defaultPeriod);
  const reports = useReports(period.from, period.to);
  const targets = useTargets();

  const report = reports.data?.report;

  const planRows = useMemo(() => {
    const t = targets.data ?? [];
    if (!t.length) return [];
    return t.filter((row) => {
      const start = row.period_start;
      const end = row.period_end;
      return start <= period.to && end >= period.from;
    });
  }, [targets.data, period.from, period.to]);

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
        <CardHeader>
          <CardTitle>План / факт</CardTitle>
        </CardHeader>
        <CardContent>
          {targets.isLoading ? (
            <PageLoading rows={1} />
          ) : !planRows.length ? (
            <p className="text-sm text-muted-foreground">план не задан</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Период</TableHead>
                  <TableHead>Менеджер</TableHead>
                  <TableHead>План</TableHead>
                  <TableHead>Факт (выиграно)</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {planRows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>
                      {formatDate(row.period_start)} — {formatDate(row.period_end)}
                    </TableCell>
                    <TableCell>{row.manager_id ?? "Компания"}</TableCell>
                    <TableCell>{formatMoney(row.amount, row.currency)}</TableCell>
                    <TableCell>{formatMoney(report?.sum_won_opportunity ?? 0, row.currency)}</TableCell>
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

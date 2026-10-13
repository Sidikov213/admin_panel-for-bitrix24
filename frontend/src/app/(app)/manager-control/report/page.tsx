"use client";

import Link from "next/link";
import { useState } from "react";
import { ErrorState, PageLoading } from "@/components/common/page-states";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useManagerControlReport } from "@/hooks/queries";
import { api } from "@/lib/api";
import { formatNumber } from "@/lib/format";

export default function ManagerControlReportPage() {
  const [period, setPeriod] = useState<"week" | "month">("week");
  const q = useManagerControlReport({ period });

  if (q.isLoading) return <PageLoading rows={8} />;
  if (q.isError)
    return <ErrorState message="Не удалось загрузить отчёт." onRetry={() => void q.refetch()} />;

  const data = q.data;
  const items = data?.items ?? [];
  const csvHref =
    data?.period?.start && data?.period?.end
      ? api.managerControlReportCsvUrl({ start: data.period.start, end: data.period.end })
      : api.managerControlReportCsvUrl();

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <Link href="/manager-control" className="text-[12px] text-muted-foreground hover:text-foreground">
            ← Контроль менеджеров
          </Link>
          <p className="mt-1 text-[13px] text-muted-foreground">
            Период: {data?.period.start} — {data?.period.end}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={period} onValueChange={(v) => setPeriod(v as "week" | "month")}>
            <SelectTrigger className="h-8 w-36 text-[13px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="week">Неделя</SelectItem>
              <SelectItem value="month">Месяц</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" asChild>
            <a href={csvHref} download="manager-control-report.csv">
              CSV
            </a>
          </Button>
        </div>
      </div>

      <div className="panel overflow-x-auto">
        <Table className="data-table">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pl-4">Менеджер</TableHead>
              <TableHead className="text-right">Раб. дней план</TableHead>
              <TableHead className="text-right">Дней с данными</TableHead>
              <TableHead className="text-right">План мин</TableHead>
              <TableHead className="text-right">Факт</TableHead>
              <TableHead className="text-right">Δ мин</TableHead>
              <TableHead className="text-right">Опоздания</TableHead>
              <TableHead className="text-right">Не закрыт</TableHead>
              <TableHead className="text-right">Нарушения</TableHead>
              <TableHead className="pr-4 text-right">CRM</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((row) => (
              <TableRow key={row.id} className="interactive-row">
                <TableCell className="pl-4">
                  <Link href={`/manager-control/${row.id}`} className="font-medium hover:text-primary">
                    {row.display_name}
                  </Link>
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatNumber(row.working_days_plan)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatNumber(row.marked_days)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatNumber(row.plan_minutes)}</TableCell>
                <TableCell className="text-right tabular-nums">{row.fact_display}</TableCell>
                <TableCell className="text-right tabular-nums">{formatNumber(row.delta_minutes)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatNumber(row.late_starts)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatNumber(row.not_closed)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatNumber(row.open_violations)}</TableCell>
                <TableCell className="pr-4 text-right tabular-nums">{formatNumber(row.crm_actions)}</TableCell>
              </TableRow>
            ))}
            {items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={10} className="py-8 text-center text-muted-foreground">
                  Нет данных за период.
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

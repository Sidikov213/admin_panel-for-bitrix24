"use client";

import Link from "next/link";
import { useState } from "react";
import { DataFreshness } from "@/components/common/data-freshness";
import { DeltaBadge } from "@/components/common/delta-badge";
import { ErrorState, PageLoading } from "@/components/common/page-states";
import { PeriodPicker, defaultPeriod, type PeriodValue } from "@/components/common/period-picker";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useManagers, useSystem } from "@/hooks/queries";
import { formatMoney, formatNumber } from "@/lib/format";

export default function ManagersPage() {
  const [period, setPeriod] = useState<PeriodValue>(defaultPeriod);
  const q = useManagers({
    preset: period.preset === "custom" ? undefined : period.preset,
    period_start: period.from,
    period_end: period.to,
  });
  const system = useSystem();

  if (q.isLoading) return <PageLoading rows={8} />;
  if (q.isError) return <ErrorState message="Не удалось загрузить менеджеров." onRetry={() => void q.refetch()} />;

  const rows = q.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[13px] text-muted-foreground">
          {rows.length} менеджеров · без общего рейтинга эффективности
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <PeriodPicker value={period} onChange={setPeriod} compact />
          <DataFreshness freshness={system.data?.freshness} compact />
        </div>
      </div>

      <div className="panel overflow-x-auto">
        <Table className="data-table">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pl-4">Менеджер</TableHead>
              <TableHead className="text-right">Активные</TableHead>
              <TableHead className="text-right">Новые</TableHead>
              <TableHead className="text-right">Выиграно</TableHead>
              <TableHead className="text-right">Проиграно</TableHead>
              <TableHead className="text-right">Сумма акт.</TableHead>
              <TableHead className="text-right">Сумма выигр.</TableHead>
              <TableHead className="text-right">Просрочки</TableHead>
              <TableHead className="text-right">Без дела</TableHead>
              <TableHead className="text-right">% без дела</TableHead>
              <TableHead className="text-right">Откр. наруш.</TableHead>
              <TableHead className="pr-4 text-right">Динамика</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((m) => (
              <TableRow key={m.id} className="interactive-row">
                <TableCell className="pl-4">
                  <Link className="font-medium text-foreground hover:text-primary" href={`/managers/${m.id}`}>
                    {m.name} {m.last_name}
                  </Link>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  <Link className="hover:underline" href={`/managers/${m.id}?metric=active`}>
                    {formatNumber(m.active_deals_count ?? 0)}
                  </Link>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  <Link className="hover:underline" href={`/managers/${m.id}?metric=new`}>
                    {formatNumber(m.new_deals_count ?? 0)}
                  </Link>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  <Link className="hover:underline" href={`/managers/${m.id}?metric=won`}>
                    {formatNumber(m.won_count ?? 0)}
                  </Link>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  <Link className="hover:underline" href={`/managers/${m.id}?metric=lost`}>
                    {formatNumber(m.lost_count ?? 0)}
                  </Link>
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatMoney(m.sum_active_opportunity)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatMoney(m.sum_won_opportunity)}</TableCell>
                <TableCell className="text-right tabular-nums">
                  <Link className="hover:underline" href={`/managers/${m.id}?metric=overdue`}>
                    {formatNumber(m.overdue_activities_unique ?? 0)}
                  </Link>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  <Link className="hover:underline" href={`/managers/${m.id}?metric=no_future`}>
                    {formatNumber(m.deals_without_future_activity_count ?? 0)}
                  </Link>
                </TableCell>
                <TableCell className="text-right tabular-nums">{m.no_future_share ?? 0}%</TableCell>
                <TableCell className="text-right tabular-nums">{formatNumber(m.open_violations ?? 0)}</TableCell>
                <TableCell className="pr-4 text-right">
                  <DeltaBadge delta={m.new_deals_delta} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

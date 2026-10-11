"use client";

import Link from "next/link";
import { useState } from "react";
import { DataFreshness } from "@/components/common/data-freshness";
import { ErrorState, PageLoading } from "@/components/common/page-states";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useOverdue, useSystem } from "@/hooks/queries";
import { formatMoney, formatNumber } from "@/lib/format";

export default function OverduePage() {
  const [groupBy, setGroupBy] = useState<string>("none");
  const [minMin, setMinMin] = useState("");
  const q = useOverdue({
    group_by: groupBy === "none" ? undefined : groupBy,
    min_overdue_minutes: minMin ? Number(minMin) : undefined,
  });
  const system = useSystem();

  if (q.isLoading) return <PageLoading rows={8} />;
  if (q.isError) return <ErrorState message="Не удалось загрузить просрочки." onRetry={() => void q.refetch()} />;

  const items = q.data?.items ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[13px] text-muted-foreground">
          {formatNumber(items.length)} просроченных дел · 1 activity = 1 overdue
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={groupBy} onValueChange={setGroupBy}>
            <SelectTrigger className="h-8 w-40 text-[13px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">Без группировки</SelectItem>
              <SelectItem value="manager">По менеджеру</SelectItem>
              <SelectItem value="pipeline">По воронке</SelectItem>
            </SelectContent>
          </Select>
          <Input
            className="h-8 w-32 text-[13px]"
            value={minMin}
            onChange={(e) => setMinMin(e.target.value)}
            placeholder="Мин. мин."
          />
          <DataFreshness freshness={system.data?.freshness} compact />
        </div>
      </div>

      <div className="panel overflow-x-auto">
        <div className="max-h-[calc(100vh-12rem)] overflow-auto">
          <Table className="data-table">
            <TableHeader className="sticky top-0 z-10 bg-card">
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-4">Сделка</TableHead>
                <TableHead>Менеджер</TableHead>
                <TableHead>Этап</TableHead>
                <TableHead className="text-right">Сумма</TableHead>
                <TableHead>Проблема</TableHead>
                <TableHead className="pr-4 font-semibold text-foreground">Длительность</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((a) => (
                <TableRow key={a.id} className="interactive-row">
                  <TableCell className="pl-4">
                    {a.deal_id ? (
                      <Link href={`/deals/${a.deal_id}`} className="font-medium hover:text-primary">
                        {a.deal_title}
                      </Link>
                    ) : (
                      a.deal_title || "—"
                    )}
                    {a.bitrix_url ? (
                      <>
                        {" · "}
                        <a href={a.bitrix_url} target="_blank" rel="noreferrer" className="text-[12px] text-primary">
                          Bitrix
                        </a>
                      </>
                    ) : null}
                  </TableCell>
                  <TableCell>{a.manager || "—"}</TableCell>
                  <TableCell className="text-muted-foreground">{a.stage || "—"}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatMoney(a.amount)}</TableCell>
                  <TableCell className="max-w-[12rem] truncate text-[13px]">{a.subject || "Просроченное дело"}</TableCell>
                  <TableCell className="pr-4 font-semibold tabular-nums text-destructive">
                    {a.overdue_label || "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}

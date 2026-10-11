"use client";

import Link from "next/link";
import { ErrorState, PageLoading } from "@/components/common/page-states";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useManagerControl } from "@/hooks/queries";
import { formatNumber } from "@/lib/format";
import { formatTimeHm, statusTone } from "@/lib/timeman-format";

export default function ManagerControlPage() {
  const q = useManagerControl();

  if (q.isLoading) return <PageLoading rows={8} />;
  if (q.isError)
    return <ErrorState message="Не удалось загрузить контроль менеджеров." onRetry={() => void q.refetch()} />;

  const data = q.data;
  const items = data?.items ?? [];
  const freshness = data?.freshness;
  const stale = Boolean(freshness?.stale);

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <p className="text-[13px] text-muted-foreground">
          Monitored sales managers · Timeman статус + CRM сегодня · без оценок эффективности
        </p>
        <div className="text-[13px]">
          <span className="text-muted-foreground">Последнее обновление Timeman: </span>
          <span className={stale ? "font-medium text-[var(--warning,#b45309)]" : "tabular-nums"}>
            {freshness?.last_updated_local ?? "—"}
          </span>
          {stale ? (
            <span className="ml-2 text-[12px] text-[var(--warning,#b45309)]">данные старше 15 мин</span>
          ) : null}
        </div>
      </div>

      {freshness?.history_since_note ? (
        <p className="text-[12px] text-muted-foreground">{freshness.history_since_note}</p>
      ) : null}

      <div className="panel overflow-x-auto">
        <Table className="data-table">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pl-4">Менеджер</TableHead>
              <TableHead>Timeman статус</TableHead>
              <TableHead>Начало сегодня</TableHead>
              <TableHead>Рабочее время сегодня</TableHead>
              <TableHead>Перерывы сегодня</TableHead>
              <TableHead className="text-right">CRM сегодня</TableHead>
              <TableHead className="text-right">Просроченные</TableHead>
              <TableHead className="text-right">Без следующего дела</TableHead>
              <TableHead className="pr-4 text-right">Последний Timeman poll</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((m) => (
              <TableRow key={m.id} className="interactive-row">
                <TableCell className="pl-4">
                  <Link
                    className="font-medium text-foreground hover:text-primary"
                    href={`/manager-control/${m.id}`}
                  >
                    {m.display_name || `${m.name} ${m.last_name}`}
                  </Link>
                </TableCell>
                <TableCell className={statusTone(m.status_normalized)} title={m.status_tooltip ?? undefined}>
                  {m.is_stale_unclosed ? (
                    <span>
                      <span className="mr-1" aria-hidden>
                        ⚠
                      </span>
                      {m.status_label}
                      {m.stale_since_label ? (
                        <span className="mt-0.5 block text-[11px] font-normal text-muted-foreground">
                          {m.stale_since_label}
                        </span>
                      ) : null}
                    </span>
                  ) : (
                    m.status_label
                  )}
                </TableCell>
                <TableCell className="tabular-nums">{formatTimeHm(m.time_start)}</TableCell>
                <TableCell className="tabular-nums">{m.duration_display ?? "—"}</TableCell>
                <TableCell className="tabular-nums">{m.time_leaks_display ?? "—"}</TableCell>
                <TableCell className="text-right tabular-nums">{formatNumber(m.crm_actions_today)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatNumber(m.overdue_activities)}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatNumber(m.no_future_activity)}
                </TableCell>
                <TableCell className="pr-4 text-right tabular-nums text-muted-foreground">
                  {m.last_timeman_poll_local ?? "—"}
                </TableCell>
              </TableRow>
            ))}
            {items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={9} className="py-8 text-center text-muted-foreground">
                  Нет monitored менеджеров (сделки в воронках 1/39 или ручное включение).
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </div>

      {freshness?.time_control ? (
        <div className="panel panel-pad opacity-70">
          <h2 className="section-title">{freshness.time_control.label}</h2>
          <p className="mt-1 text-[13px] text-muted-foreground">Idle / Offline / Desktop activity</p>
          <p className="mt-2 text-[13px]">{freshness.time_control.status}</p>
        </div>
      ) : null}
    </div>
  );
}

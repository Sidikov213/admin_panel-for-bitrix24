"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ErrorState, PageLoading } from "@/components/common/page-states";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useManagerControlDetail } from "@/hooks/queries";
import { formatNumber } from "@/lib/format";
import { formatDateShort, formatTimeHm, statusTone } from "@/lib/timeman-format";

export default function ManagerControlDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const q = useManagerControlDetail(id);

  if (q.isLoading) return <PageLoading rows={8} />;
  if (q.isError || !q.data)
    return (
      <ErrorState message="Не удалось загрузить карточку контроля." onRetry={() => void q.refetch()} />
    );

  const data = q.data;
  const cur = data.today.current_status;
  const wd = data.today.workday;
  const crm = data.today.crm_activity;
  const freshness = data.freshness;
  const stale = Boolean(freshness?.stale);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link href="/manager-control" className="text-[12px] text-muted-foreground hover:text-foreground">
            ← Контроль менеджеров
          </Link>
          <h1 className="page-title mt-1 text-[1.5rem]">{data.display_name}</h1>
        </div>
        <div className="text-[13px]">
          <span className="text-muted-foreground">Последнее обновление Timeman: </span>
          <span className={stale ? "font-medium text-[var(--warning,#b45309)]" : "tabular-nums"}>
            {cur?.last_timeman_poll_local ?? freshness?.last_updated_local ?? "—"}
          </span>
        </div>
      </div>

      <section className="grid grid-cols-2 gap-x-6 gap-y-4 border-y border-border py-4 sm:grid-cols-3 lg:grid-cols-5">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Статус</div>
          <div className={`mt-0.5 text-[15px] font-medium ${statusTone(cur?.status_normalized)}`} title={cur?.tooltip ?? undefined}>
            {cur?.is_stale_unclosed ? (
              <>
                <span aria-hidden>⚠ </span>
                {cur.status_label}
                {cur.stale_since_label ? (
                  <span className="mt-0.5 block text-[12px] font-normal text-muted-foreground">
                    {cur.stale_since_label}
                  </span>
                ) : null}
              </>
            ) : (
              (cur?.status_label ?? "—")
            )}
          </div>
        </div>
        <Strip label="Начало сегодня" value={formatTimeHm(wd?.time_start)} />
        <Strip label="Окончание сегодня" value={formatTimeHm(wd?.time_finish)} />
        <Strip label="Рабочее время сегодня" value={wd?.duration_display ?? "—"} />
        <Strip label="Перерывы сегодня" value={wd?.time_leaks_display ?? "—"} />
      </section>

      {wd?.note ? <p className="text-[13px] text-[var(--warning,#b45309)]">{wd.note}</p> : null}
      {cur?.tooltip && cur.is_stale_unclosed ? (
        <p className="text-[12px] text-muted-foreground">{cur.tooltip}</p>
      ) : null}

      <section>
        <h2 className="section-title mb-3">Timeline рабочего дня</h2>
        {data.today.timeline.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">
            {cur?.is_stale_unclosed
              ? "Stale EXPIRED не включается в сегодняшний timeline."
              : "Нет данных Timeman за сегодня для timeline."}
          </p>
        ) : (
          <ol className="space-y-2 border-l border-border pl-4">
            {data.today.timeline.map((ev, i) => (
              <li key={`${ev.kind}-${i}`} className="text-[13px]">
                <span className="font-medium">{ev.label}</span>
                {ev.at ? <span className="ml-2 tabular-nums text-muted-foreground">{formatTimeHm(ev.at)}</span> : null}
                {ev.duration_display ? (
                  <span className="ml-2 tabular-nums text-muted-foreground">{ev.duration_display}</span>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </section>

      <section>
        <h2 className="section-title mb-3">CRM activity сегодня</h2>
        <div className="grid grid-cols-2 gap-x-6 gap-y-3 border-y border-border py-4 sm:grid-cols-4 lg:grid-cols-7">
          <Strip label="Созданные сделки" value={formatNumber(crm.created_deals)} />
          <Strip label="Изменённые сделки" value={formatNumber(crm.changed_deals)} />
          <Strip label="Завершённые дела" value={formatNumber(crm.completed_activities)} />
          <Strip label="Смены стадии" value={formatNumber(crm.stage_changes)} />
          <Strip label="Смены суммы" value={formatNumber(crm.opportunity_changes)} />
          <Strip label="Просроченные" value={formatNumber(crm.overdue_activities)} />
          <Strip label="Без следующего дела" value={formatNumber(crm.no_future_activity)} />
        </div>
      </section>

      <section>
        <h2 className="section-title mb-2">Неделя</h2>
        {freshness?.history_since_note ? (
          <p className="mb-3 text-[12px] text-muted-foreground">{freshness.history_since_note}</p>
        ) : null}
        <div className="panel overflow-x-auto">
          <Table className="data-table">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-4">Дата</TableHead>
                <TableHead>Начало</TableHead>
                <TableHead>Окончание</TableHead>
                <TableHead>Рабочее время</TableHead>
                <TableHead>Перерывы</TableHead>
                <TableHead className="pr-4 text-right">CRM activity</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.week.map((row) => {
                const crmDay =
                  (row.crm_activity?.created_deals ?? 0) +
                  (row.crm_activity?.completed_activities ?? 0) +
                  (row.crm_activity?.changed_deals ?? 0);
                return (
                  <TableRow key={row.date}>
                    <TableCell className="pl-4">{formatDateShort(row.date)}</TableCell>
                    {row.workday_available ? (
                      <>
                        <TableCell className="tabular-nums">{formatTimeHm(row.time_start)}</TableCell>
                        <TableCell className="tabular-nums">{formatTimeHm(row.time_finish)}</TableCell>
                        <TableCell className="tabular-nums">{row.duration_display ?? "—"}</TableCell>
                        <TableCell className="tabular-nums">{row.time_leaks_display ?? "—"}</TableCell>
                      </>
                    ) : (
                      <TableCell colSpan={4} className="text-[12px] text-muted-foreground">
                        {row.note ?? "Нет локальной истории рабочего времени за этот день"}
                      </TableCell>
                    )}
                    <TableCell className="pr-4 text-right tabular-nums">{formatNumber(crmDay)}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </section>

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

function Strip({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-[15px] font-medium tabular-nums">{value}</div>
    </div>
  );
}

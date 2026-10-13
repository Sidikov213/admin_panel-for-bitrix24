"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ErrorState, PageLoading } from "@/components/common/page-states";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useManagerControlDetail, useManagerControlWeek } from "@/hooks/queries";
import { formatNumber } from "@/lib/format";
import { formatDateShort, formatTimeHm, statusTone } from "@/lib/timeman-format";
import { getViolationLabel } from "@/lib/ui-labels";

function severityVariant(severity: string): "warning" | "destructive" | "secondary" {
  if (severity === "critical" || severity === "high") return "destructive";
  if (severity === "medium") return "warning";
  return "secondary";
}

export default function ManagerControlDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const q = useManagerControlDetail(id);
  const weekQ = useManagerControlWeek(id);

  if (q.isLoading) return <PageLoading rows={8} />;
  if (q.isError || !q.data)
    return (
      <ErrorState message="Не удалось загрузить карточку контроля." onRetry={() => void q.refetch()} />
    );

  const data = q.data;
  const cur = data.today.current_status;
  const wd = data.today.workday;
  const crm = data.today.crm_activity;
  const schedule = data.today.schedule;
  const violations = data.today.violations;
  const freshness = data.freshness;
  const stale = Boolean(freshness?.stale);
  const weekRows = weekQ.data?.rows ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link href="/manager-control" className="text-[12px] text-muted-foreground hover:text-foreground">
            ← Контроль менеджеров
          </Link>
          <h1 className="page-title mt-1 text-[1.5rem]">{data.display_name}</h1>
        </div>
        <div className="flex flex-wrap gap-3 text-[13px]">
          <Link href="/manager-control/report" className="text-primary hover:underline">
            Отчёт команды
          </Link>
          <span className="text-muted-foreground">
            Timeman:{" "}
            <span className={stale ? "font-medium text-[var(--warning,#b45309)]" : "tabular-nums"}>
              {cur?.last_timeman_poll_local ?? freshness?.last_updated_local ?? "—"}
            </span>
          </span>
        </div>
      </div>

      {data.limitations?.note ? (
        <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-[12px] text-muted-foreground">
          {data.limitations.note}
        </p>
      ) : null}

      <section className="panel panel-pad space-y-3">
        <h2 className="section-title">Сегодня · план и факт</h2>
        {!schedule?.configured ? (
          <p className="text-[13px] text-muted-foreground">
            {schedule?.label ?? "Рабочий график не настроен"}
          </p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 text-[13px]">
            <div>
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">График</div>
              <div className="mt-0.5 font-medium">{schedule.name}</div>
              <div className="tabular-nums text-muted-foreground">
                {schedule.is_working
                  ? `${schedule.planned_start ?? "—"} – ${schedule.planned_end ?? "—"}`
                  : `Выходной (${schedule.kind ?? "—"})`}
              </div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Факт начало / конец</div>
              <div className="mt-0.5 tabular-nums font-medium">
                {formatTimeHm(wd?.time_start)} – {formatTimeHm(wd?.time_finish)}
              </div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Отработано / перерывы</div>
              <div className="mt-0.5 tabular-nums font-medium">
                {wd?.duration_display ?? "—"} · {wd?.time_leaks_display ?? "—"}
              </div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Статус</div>
              <div className={`mt-0.5 font-medium ${statusTone(cur?.status_normalized)}`}>
                {cur?.is_stale_unclosed ? (
                  <>
                    <span aria-hidden>⚠ </span>
                    {cur.status_label}
                  </>
                ) : (
                  (cur?.status_label ?? "—")
                )}
              </div>
            </div>
          </div>
        )}
        {wd?.note ? <p className="text-[13px] text-[var(--warning,#b45309)]">{wd.note}</p> : null}
      </section>

      <section>
        <h2 className="section-title mb-3">Нарушения сегодня</h2>
        {!violations || (violations.open.length === 0 && violations.resolved.length === 0) ? (
          <p className="text-[13px] text-muted-foreground">Нет нарушений за сегодня.</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="panel panel-pad">
              <h3 className="text-[12px] font-medium uppercase tracking-wide text-muted-foreground">Открытые</h3>
              <ul className="mt-2 space-y-2">
                {violations.open.length === 0 ? (
                  <li className="text-[13px] text-muted-foreground">—</li>
                ) : (
                  violations.open.map((v) => (
                    <li key={`${v.type}-${v.detected_at}`} className="flex flex-wrap items-center gap-2 text-[13px]">
                      <Badge variant={severityVariant(v.severity)} className="text-[10px] font-normal">
                        {v.label && !/^[A-Z_]+$/.test(v.label) ? v.label : getViolationLabel(v.type)}
                      </Badge>
                      {v.is_preview ? (
                        <span className="text-[11px] text-muted-foreground">предпросмотр</span>
                      ) : null}
                    </li>
                  ))
                )}
              </ul>
            </div>
            <div className="panel panel-pad">
              <h3 className="text-[12px] font-medium uppercase tracking-wide text-muted-foreground">Закрытые</h3>
              <ul className="mt-2 space-y-2">
                {violations.resolved.length === 0 ? (
                  <li className="text-[13px] text-muted-foreground">—</li>
                ) : (
                  violations.resolved.map((v) => (
                    <li key={`${v.type}-${v.resolved_at}`} className="text-[13px] text-muted-foreground">
                      {v.label && !/^[A-Z_]+$/.test(v.label) ? v.label : getViolationLabel(v.type)}
                      {v.resolved_at ? (
                        <span className="ml-2 tabular-nums">{formatTimeHm(v.resolved_at)}</span>
                      ) : null}
                    </li>
                  ))
                )}
              </ul>
            </div>
          </div>
        )}
      </section>

      <section>
        <h2 className="section-title mb-3">CRM сегодня</h2>
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
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="section-title">Неделя</h2>
          <Link href="/manager-control/report" className="text-[12px] text-primary hover:underline">
            Сводный отчёт команды →
          </Link>
        </div>
        {weekQ.isLoading ? (
          <p className="text-[13px] text-muted-foreground">Загрузка недели…</p>
        ) : weekQ.isError ? (
          <p className="text-[13px] text-muted-foreground">Не удалось загрузить недельный отчёт.</p>
        ) : (
          <>
            {weekQ.data?.totals ? (
              <p className="mb-3 text-[12px] text-muted-foreground">
                {weekQ.data.period.start} — {weekQ.data.period.end} · факт {weekQ.data.totals.fact_display} · Δ{" "}
                {weekQ.data.totals.delta_minutes} мин · нарушений {weekQ.data.totals.open_violations}
              </p>
            ) : null}
            <div className="panel overflow-x-auto">
              <Table className="data-table">
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-4">Дата</TableHead>
                    <TableHead>План</TableHead>
                    <TableHead>Начало</TableHead>
                    <TableHead>Конец</TableHead>
                    <TableHead>Отработано</TableHead>
                    <TableHead>Нарушения</TableHead>
                    <TableHead className="pr-4 text-right">CRM</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {weekRows.map((row) => (
                    <TableRow key={row.date}>
                      <TableCell className="pl-4">{formatDateShort(row.date)}</TableCell>
                      <TableCell className="text-[12px] text-muted-foreground">
                        {row.no_historical_data
                          ? (row.missing_data_label ?? "—")
                          : row.plan?.is_working
                            ? `${row.plan.start ?? "—"}–${row.plan.end ?? "—"}`
                            : "Выходной"}
                      </TableCell>
                      <TableCell className="tabular-nums">{formatTimeHm(row.time_start)}</TableCell>
                      <TableCell className="tabular-nums">{formatTimeHm(row.time_finish)}</TableCell>
                      <TableCell className="tabular-nums">{row.duration_display ?? "—"}</TableCell>
                      <TableCell>
                        {row.violations?.length ? (
                          <span className="text-[12px]">
                            {row.violations
                              .map((v) =>
                                v.label && !/^[A-Z_]+$/.test(v.label) ? v.label : getViolationLabel(v.type),
                              )
                              .join(", ")}
                          </span>
                        ) : (
                          "—"
                        )}
                      </TableCell>
                      <TableCell className="pr-4 text-right tabular-nums">
                        {formatNumber(row.crm_actions ?? 0)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </>
        )}
      </section>
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

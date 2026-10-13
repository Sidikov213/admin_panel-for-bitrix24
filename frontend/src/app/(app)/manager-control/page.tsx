"use client";

import Link from "next/link";
import { useState } from "react";
import { ErrorState, PageLoading } from "@/components/common/page-states";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useManagerControl } from "@/hooks/queries";
import { formatNumber } from "@/lib/format";
import { formatTimeHm, statusTone } from "@/lib/timeman-format";
import { getViolationLabel } from "@/lib/ui-labels";
import type { ManagerControlViolationBadge } from "@/types/api";

function violationBadgeVariant(severity: string): "warning" | "destructive" | "secondary" | "outline" {
  if (severity === "critical" || severity === "high") return "destructive";
  if (severity === "medium") return "warning";
  return "secondary";
}

function ViolationsCell({
  count,
  badges,
}: {
  count?: number;
  badges?: ManagerControlViolationBadge[];
}) {
  const n = count ?? 0;
  if (n === 0) return <span className="text-muted-foreground">—</span>;
  if (badges?.length) {
    return (
      <div className="flex max-w-[220px] flex-wrap gap-1">
        {badges.map((b) => (
          <Badge key={b.type} variant={violationBadgeVariant(b.severity)} className="text-[10px] font-normal">
            {b.label && !/^[A-Z_]+$/.test(b.label) ? b.label : getViolationLabel(b.type)}
            {b.is_preview ? " · предпросмотр" : ""}
          </Badge>
        ))}
        {n > badges.length ? (
          <span className="text-[11px] text-muted-foreground">+{n - badges.length}</span>
        ) : null}
      </div>
    );
  }
  return <span className="text-[13px]">{n} нарушений</span>;
}

export default function ManagerControlPage() {
  const q = useManagerControl();
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [violationsFilter, setViolationsFilter] = useState<string>("all");
  const [search, setSearch] = useState("");

  if (q.isLoading) return <PageLoading rows={8} />;
  if (q.isError)
    return <ErrorState message="Не удалось загрузить контроль менеджеров." onRetry={() => void q.refetch()} />;

  const data = q.data;
  const items = data?.items ?? [];
  const qLower = search.trim().toLowerCase();
  const filtered = items.filter((m) => {
    if (statusFilter !== "all" && m.status_normalized !== statusFilter) return false;
    if (violationsFilter === "yes" && !m.has_violations) return false;
    if (violationsFilter === "no" && m.has_violations) return false;
    if (qLower) {
      const hay = `${m.display_name} ${m.name} ${m.last_name}`.toLowerCase();
      if (!hay.includes(qLower)) return false;
    }
    return true;
  });
  const freshness = data?.freshness;
  const stale = Boolean(freshness?.stale);

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <p className="text-[13px] text-muted-foreground">
          Timeman + график + нарушения · CRM отдельно · без оценок эффективности
        </p>
        <div className="flex flex-wrap items-center gap-3 text-[13px]">
          <Link href="/manager-control/report" className="text-primary hover:underline">
            Отчёт команды
          </Link>
          <Link href="/admin/manager-control" className="text-muted-foreground hover:text-foreground">
            Админ графиков
          </Link>
        </div>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap gap-2">
          <Input
            placeholder="Поиск менеджера"
            className="h-8 w-44 text-[13px]"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="h-8 w-40 text-[13px]">
              <SelectValue placeholder="Статус" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все статусы</SelectItem>
              <SelectItem value="working">Работает</SelectItem>
              <SelectItem value="paused">Перерыв</SelectItem>
              <SelectItem value="closed">Закрыт</SelectItem>
              <SelectItem value="not_started">Не начат</SelectItem>
              <SelectItem value="no_data">Нет данных</SelectItem>
              <SelectItem value="stale_unclosed">Незакрытый</SelectItem>
            </SelectContent>
          </Select>
          <Select value={violationsFilter} onValueChange={setViolationsFilter}>
            <SelectTrigger className="h-8 w-44 text-[13px]">
              <SelectValue placeholder="Нарушения" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все</SelectItem>
              <SelectItem value="yes">С нарушениями</SelectItem>
              <SelectItem value="no">Без нарушений</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="text-[13px]">
          <span className="text-muted-foreground">Timeman: </span>
          <span className={stale ? "font-medium text-[var(--warning,#b45309)]" : "tabular-nums"}>
            {freshness?.last_updated_local ?? "—"}
          </span>
          {stale ? (
            <span className="ml-2 text-[12px] text-[var(--warning,#b45309)]">старше 15 мин</span>
          ) : null}
        </div>
      </div>

      {data?.limitations?.note ? (
        <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-[12px] text-muted-foreground">
          {data.limitations.note}
        </p>
      ) : null}

      {freshness?.history_since_note ? (
        <p className="text-[12px] text-muted-foreground">{freshness.history_since_note}</p>
      ) : null}

      <div className="panel overflow-x-auto">
        <Table className="data-table">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pl-4">Менеджер</TableHead>
              <TableHead>Статус</TableHead>
              <TableHead>Начало</TableHead>
              <TableHead>Окончание</TableHead>
              <TableHead>Отработано</TableHead>
              <TableHead>Перерывы</TableHead>
              <TableHead className="text-right">CRM сегодня</TableHead>
              <TableHead>Нарушения</TableHead>
              <TableHead className="pr-4 text-right">Обновление</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((m) => (
              <TableRow key={m.id} className="interactive-row">
                <TableCell className="pl-4">
                  <Link
                    className="font-medium text-foreground hover:text-primary"
                    href={`/manager-control/${m.id}`}
                  >
                    {m.display_name || `${m.name} ${m.last_name}`}
                  </Link>
                  {m.schedule && !m.schedule.configured ? (
                    <p className="mt-0.5 text-[11px] text-muted-foreground">{m.schedule.label}</p>
                  ) : null}
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
                <TableCell className="tabular-nums">{formatTimeHm(m.time_finish)}</TableCell>
                <TableCell className="tabular-nums">{m.duration_display ?? "—"}</TableCell>
                <TableCell className="tabular-nums">{m.time_leaks_display ?? "—"}</TableCell>
                <TableCell className="text-right tabular-nums">{formatNumber(m.crm_actions_today)}</TableCell>
                <TableCell>
                  <ViolationsCell count={m.violations_count} badges={m.violation_badges} />
                </TableCell>
                <TableCell className="pr-4 text-right tabular-nums text-muted-foreground">
                  {m.last_timeman_poll_local ?? "—"}
                </TableCell>
              </TableRow>
            ))}
            {filtered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={9} className="py-8 text-center text-muted-foreground">
                  {items.length === 0
                    ? "Нет monitored менеджеров (сделки в воронках 1/39 или ручное включение)."
                    : "Нет строк по фильтрам."}
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </div>

      <p className="text-[12px] text-muted-foreground">
        Показано {filtered.length} из {items.length}
        {data?.policy?.enforcement_start_date
          ? ` · контроль с ${data.policy.enforcement_start_date}`
          : ""}
      </p>
    </div>
  );
}

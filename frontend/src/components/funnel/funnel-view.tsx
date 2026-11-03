"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useFunnel, useManagers, usePipelines } from "@/hooks/queries";
import { formatMoney, formatNumber, formatPercent, managerName } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { FunnelResponse } from "@/types/api";

const RANGES = [
  { days: 30, label: "30 дней" },
  { days: 90, label: "90 дней" },
  { days: 180, label: "Полгода" },
  { days: 365, label: "Год" },
];

function isoDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function rangeFor(days: number): { from: string; to: string } {
  const to = new Date();
  const from = new Date(to.getFullYear(), to.getMonth(), to.getDate() - (days - 1));
  return { from: isoDate(from), to: isoDate(to) };
}

function formatDays(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${formatNumber(v)} дн.`;
}

const selectClass =
  "flex h-10 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function FunnelView() {
  const pipelines = usePipelines();
  const managers = useManagers();
  const [categoryId, setCategoryId] = useState<number | undefined>(undefined);
  const [rangeDays, setRangeDays] = useState<number | null>(90);
  const [period, setPeriod] = useState(() => rangeFor(90));
  const [managerId, setManagerId] = useState("");

  const funnel = useFunnel({
    category_id: categoryId,
    period_start: period.from,
    period_end: period.to,
    manager_id: managerId ? Number(managerId) : undefined,
  });

  const sortedManagers = useMemo(
    () => (managers.data ?? []).slice().sort((a, b) => managerName(a).localeCompare(managerName(b))),
    [managers.data],
  );
  const pipelineList = (pipelines.data ?? []).filter((p) => p.stages.length);
  const activeCategory = categoryId ?? funnel.data?.pipeline.category_id;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-serif text-3xl font-semibold">Воронки</h1>
        <p className="text-sm text-muted-foreground">Конверсия по этапам, скорость сделок и где они теряются</p>
      </div>

      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        {pipelineList.length > 1 ? (
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="Воронка">
            {pipelineList.map((p) => {
              const bid = Number(p.bitrix_id);
              const selected = bid === activeCategory;
              return (
                <button
                  key={p.id}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  onClick={() => setCategoryId(bid)}
                  className={cn(
                    "rounded-lg border px-3 py-2 text-sm transition-colors",
                    selected ? "border-primary bg-primary text-primary-foreground" : "border-border hover:bg-muted",
                  )}
                >
                  {p.name}
                </button>
              );
            })}
          </div>
        ) : (
          <div />
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:flex lg:items-end">
          <div className="space-y-1">
            <Label htmlFor="funnel-range">Период</Label>
            <select
              id="funnel-range"
              className={cn(selectClass, "lg:w-36")}
              value={rangeDays ?? "custom"}
              onChange={(e) => {
                if (e.target.value === "custom") {
                  setRangeDays(null);
                  return;
                }
                const days = Number(e.target.value);
                setRangeDays(days);
                setPeriod(rangeFor(days));
              }}
            >
              {RANGES.map((r) => (
                <option key={r.days} value={r.days}>
                  {r.label}
                </option>
              ))}
              <option value="custom">Свои даты</option>
            </select>
          </div>
          {rangeDays === null ? (
            <div className="flex gap-2 sm:col-span-2 lg:col-span-1">
              <div className="space-y-1">
                <Label htmlFor="funnel-from">С</Label>
                <Input id="funnel-from" type="date" value={period.from} onChange={(e) => setPeriod((p) => ({ ...p, from: e.target.value }))} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="funnel-to">По</Label>
                <Input id="funnel-to" type="date" value={period.to} onChange={(e) => setPeriod((p) => ({ ...p, to: e.target.value }))} />
              </div>
            </div>
          ) : null}
          <div className="space-y-1">
            <Label htmlFor="funnel-manager">Менеджер</Label>
            <select
              id="funnel-manager"
              className={cn(selectClass, "lg:w-52")}
              value={managerId}
              onChange={(e) => setManagerId(e.target.value)}
            >
              <option value="">Все менеджеры</option>
              {sortedManagers.map((m) => (
                <option key={m.id} value={m.id}>
                  {managerName(m)}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {funnel.isLoading ? (
        <PageLoading rows={4} />
      ) : funnel.isError ? (
        <ErrorState message="Не удалось посчитать воронку." onRetry={() => void funnel.refetch()} />
      ) : funnel.data ? (
        <FunnelBody data={funnel.data} managerFiltered={!!managerId} />
      ) : null}
    </div>
  );
}

function FunnelBody({ data, managerFiltered }: { data: FunnelResponse; managerFiltered: boolean }) {
  const { summary } = data;
  const first = data.funnel[0]?.reached ?? 0;
  const timed = data.stage_time.filter((s) => s.median_days !== null);
  const slowest = timed.reduce<string | null>(
    (acc, s) =>
      acc === null || (s.median_days ?? 0) > (timed.find((t) => t.stage_id === acc)?.median_days ?? 0) ? s.stage_id : acc,
    null,
  );
  // The weakest step: biggest drop between consecutive stages
  const weakest = data.funnel
    .slice(1)
    .filter((s) => s.conversion_from_prev !== null)
    .reduce<(typeof data.funnel)[number] | null>(
      (acc, s) => (acc === null || (s.conversion_from_prev ?? 100) < (acc.conversion_from_prev ?? 100) ? s : acc),
      null,
    );

  return (
    <div className="space-y-6">
      {data.data_quality.note ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {data.data_quality.note}
        </p>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat title="Создано сделок" value={formatNumber(summary.created)} hint="в выбранном периоде" />
        <Stat
          title="Выиграно"
          value={formatNumber(summary.won)}
          hint={summary.won ? `на ${formatMoney(summary.won_amount)}` : "закрыто в периоде"}
        />
        <Stat
          title="Доля выигранных"
          value={formatPercent(summary.win_rate)}
          hint={`${summary.won} выиграно · ${summary.lost} проиграно`}
        />
        <Stat
          title="Цикл сделки"
          value={formatDays(summary.cycle_won.median_days)}
          hint="медиана от создания до выигрыша"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Воронка «{data.pipeline.name}»</CardTitle>
          <CardDescription>{data.definitions.funnel}</CardDescription>
        </CardHeader>
        <CardContent>
          {!first ? (
            <EmptyState title="В периоде не создано ни одной сделки" />
          ) : (
            <ol className="space-y-3">
              {data.funnel.map((s, i) => {
                const width = first ? Math.max(2, (s.reached / first) * 100) : 0;
                const isWeak = weakest?.stage_id === s.stage_id;
                return (
                  <li key={s.stage_id} className="grid gap-1 sm:grid-cols-[minmax(0,14rem)_1fr_auto] sm:items-center sm:gap-3">
                    <span className="truncate text-sm font-medium" title={s.name}>
                      {s.name}
                    </span>
                    <div className="h-7 w-full rounded-md bg-muted">
                      <div
                        className={cn(
                          "flex h-full items-center rounded-md px-2 text-xs font-medium text-white",
                          s.kind === "won" ? "bg-emerald-600" : "bg-primary",
                        )}
                        style={{ width: `${width}%` }}
                      >
                        {formatNumber(s.reached)}
                      </div>
                    </div>
                    <span className="text-sm text-muted-foreground sm:w-44 sm:text-right">
                      {i === 0 ? (
                        "100 %"
                      ) : (
                        <>
                          <span className={cn(isWeak && "font-semibold text-red-700")}>
                            {formatPercent(s.conversion_from_prev)} от пред.
                          </span>
                          {" · "}
                          {formatPercent(s.conversion_from_start)}
                        </>
                      )}
                    </span>
                  </li>
                );
              })}
            </ol>
          )}
          {weakest && first ? (
            <p className="mt-4 text-sm text-muted-foreground">
              Самый большой отсев — на переходе к этапу «{weakest.name}»: доходит {formatPercent(weakest.conversion_from_prev)}.
            </p>
          ) : null}
        </CardContent>
      </Card>

      {/* min-w-0: grid items must shrink so wide tables scroll inside the card, not the page */}
      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="min-w-0 xl:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">Время на этапах</CardTitle>
            <CardDescription>{data.definitions.stage_time}</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Этап</TableHead>
                  <TableHead>Медиана</TableHead>
                  <TableHead>Среднее</TableHead>
                  <TableHead>Переходов</TableHead>
                  <TableHead>Сейчас на этапе</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.stage_time.map((s) => (
                  <TableRow key={s.stage_id}>
                    <TableCell className="font-medium">
                      {s.name}
                      {s.stage_id === slowest && timed.length > 1 ? (
                        <Badge variant="warning" className="ml-2 whitespace-nowrap">
                          дольше всего
                        </Badge>
                      ) : null}
                    </TableCell>
                    <TableCell>{formatDays(s.median_days)}</TableCell>
                    <TableCell>{formatDays(s.avg_days)}</TableCell>
                    <TableCell>{formatNumber(s.count)}</TableCell>
                    <TableCell>
                      {s.current_count ? `${formatNumber(s.current_count)} · ${formatDays(s.current_median_days)}` : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card className="min-w-0">
          <CardHeader>
            <CardTitle className="text-base">Где теряем сделки</CardTitle>
            <CardDescription>{data.definitions.losses}</CardDescription>
          </CardHeader>
          <CardContent>
            {!data.losses.length ? (
              <p className="text-sm text-muted-foreground">Проигранных сделок в периоде нет.</p>
            ) : (
              <ul className="space-y-3">
                {data.losses.map((l) => (
                  <li key={l.stage_id} className="space-y-1">
                    <div className="flex justify-between gap-2 text-sm">
                      <span className="truncate">{l.name}</span>
                      <span className="text-muted-foreground">
                        {formatNumber(l.count)} · {formatPercent(l.share)}
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-muted">
                      <div className="h-full rounded-full bg-red-600" style={{ width: `${l.share}%` }} />
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-4 text-xs text-muted-foreground">
              Цикл проигранной сделки: {formatDays(data.summary.cycle_lost.median_days)} (медиана)
            </p>
          </CardContent>
        </Card>
      </div>

      {!managerFiltered && data.managers.length ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">По менеджерам</CardTitle>
            <CardDescription>{data.definitions.win_rate}</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Менеджер</TableHead>
                  <TableHead>Создано</TableHead>
                  <TableHead>Выиграно</TableHead>
                  <TableHead>Проиграно</TableHead>
                  <TableHead>Доля выигранных</TableHead>
                  <TableHead>Сумма</TableHead>
                  <TableHead>Цикл</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.managers.map((m) => (
                  <TableRow key={m.manager_id}>
                    <TableCell>
                      <Link href={`/managers/${m.manager_id}`} className="text-primary hover:underline">
                        {m.name}
                      </Link>
                    </TableCell>
                    <TableCell>{formatNumber(m.created)}</TableCell>
                    <TableCell>{formatNumber(m.won)}</TableCell>
                    <TableCell>{formatNumber(m.lost)}</TableCell>
                    <TableCell>{formatPercent(m.win_rate)}</TableCell>
                    <TableCell className="whitespace-nowrap">{formatMoney(m.won_amount)}</TableCell>
                    <TableCell>{formatDays(m.cycle_won_median_days)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function Stat({ title, value, hint }: { title: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="font-serif text-2xl font-semibold">{value}</p>
        {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}

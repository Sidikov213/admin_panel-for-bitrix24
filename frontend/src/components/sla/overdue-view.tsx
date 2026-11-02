"use client";

import Link from "next/link";
import { useState } from "react";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { BitrixLink, ScopeFilters, selectClass } from "@/components/common/scope-filters";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useOverdue, usePipelines } from "@/hooks/queries";
import { formatDate, formatDateTime, formatDuration } from "@/lib/format";

const PERIODS = [
  { value: "today", label: "Сегодня" },
  { value: "yesterday", label: "Вчера" },
  { value: "week", label: "Неделя" },
  { value: "month", label: "Месяц" },
];
const PAGE = 50;

export function OverdueView() {
  const [period, setPeriod] = useState("week");
  const [categoryId, setCategoryId] = useState<number | undefined>();
  const [managerId, setManagerId] = useState<number | undefined>();
  const [stageId, setStageId] = useState<number | undefined>();
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [page, setPage] = useState(0);
  const pipelines = usePipelines();
  const stages = (pipelines.data ?? [])
    .filter((p) => categoryId === undefined || Number(p.bitrix_id) === categoryId)
    .flatMap((p) => p.stages.map((s) => ({ ...s, pipeline: p.name })));
  const q = useOverdue({
    period,
    category_id: categoryId,
    manager_id: managerId,
    stage_id: stageId,
    only_open: onlyOpen || undefined,
    offset: page * PAGE,
    limit: PAGE,
  });
  const d = q.data;
  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setPage(0);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-serif text-3xl font-semibold">Просроченные дела</h1>
        <p className="text-sm text-muted-foreground">
          Дела, срок которых пришёлся на период и был пропущен: висят до сих пор или закрыты позже срока.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Период">
          {PERIODS.map((p) => (
            <Button
              key={p.value}
              size="sm"
              className="h-10"
              variant={period === p.value ? "default" : "outline"}
              role="tab"
              aria-selected={period === p.value}
              onClick={() => reset(setPeriod)(p.value)}
            >
              {p.label}
            </Button>
          ))}
        </div>
        <ScopeFilters
          idPrefix="overdue"
          categoryId={categoryId}
          managerId={managerId}
          onCategory={(v) => {
            reset(setCategoryId)(v);
            setStageId(undefined);
          }}
          onManager={reset(setManagerId)}
        />
        <div className="w-full space-y-1.5 sm:w-56">
          <Label htmlFor="overdue-stage" className="block text-xs text-muted-foreground">
            Стадия сделки
          </Label>
          <select
            id="overdue-stage"
            className={selectClass}
            value={stageId ?? ""}
            onChange={(e) => reset(setStageId)(e.target.value ? Number(e.target.value) : undefined)}
          >
            <option value="">Все стадии</option>
            {stages.map((s) => (
              <option key={s.id} value={s.id}>
                {categoryId === undefined ? `${s.pipeline}: ${s.name}` : s.name}
              </option>
            ))}
          </select>
        </div>
        <label className="flex h-10 items-center gap-2 text-sm">
          <input type="checkbox" checked={onlyOpen} onChange={(e) => reset(setOnlyOpen)(e.target.checked)} />
          Только незакрытые
        </label>
      </div>

      {q.isLoading && !d ? (
        <PageLoading rows={3} />
      ) : q.isError ? (
        <ErrorState message="Не удалось загрузить просрочки." onRetry={() => void q.refetch()} />
      ) : d ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Stat title="Просрочено за период" value={String(d.summary.total)} hint={`${formatDate(d.date_from)} — ${formatDate(d.date_to)}`} />
            <Stat title="Висят до сих пор" value={String(d.summary.open)} />
            <Stat title="Закрыто с опозданием" value={String(d.summary.closed_late)} />
            <Stat
              title="Закрывали после срока"
              value={formatDuration(d.summary.close_delay_median_seconds)}
              hint="медиана: сколько прошло от срока до закрытия"
            />
          </div>
          {d.summary.unknown_completion ? (
            <p className="text-xs text-muted-foreground">
              Ещё {d.summary.unknown_completion} закрытых дел без известного времени закрытия не учтены. Оно появится после
              следующей полной синхронизации.
            </p>
          ) : null}

          {!d.items.length ? (
            <EmptyState title="Просрочек нет" />
          ) : (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Дела</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Дело</TableHead>
                      <TableHead>Сделка</TableHead>
                      <TableHead>Срок</TableHead>
                      <TableHead>Просрочено на</TableHead>
                      <TableHead>Статус</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {d.items.map((a) => (
                      <TableRow key={a.activity_id}>
                        <TableCell>
                          {a.type}
                          {a.subject ? <p className="text-xs text-muted-foreground">{a.subject}</p> : null}
                        </TableCell>
                        <TableCell>
                          <Link href={`/deals/${a.deal_id}`} className="font-medium text-primary hover:underline">
                            №{a.deal_bitrix_id} {a.deal_title}
                          </Link>
                          <p className="text-xs text-muted-foreground">
                            {[a.manager, a.pipeline, a.stage].filter(Boolean).join(" · ")}
                          </p>
                          <BitrixLink href={a.bitrix_url} />
                        </TableCell>
                        <TableCell className="whitespace-nowrap">{formatDateTime(a.deadline)}</TableCell>
                        <TableCell className="whitespace-nowrap">{formatDuration(a.overdue_seconds)}</TableCell>
                        <TableCell className="whitespace-nowrap">
                          {a.is_open ? (
                            <Badge variant="destructive">не закрыто</Badge>
                          ) : (
                            <>
                              <Badge variant="secondary">закрыто</Badge>
                              <p className="text-xs text-muted-foreground">{formatDateTime(a.completed_at)}</p>
                            </>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <div className="mt-4 flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">
                    Всего: {d.total} · Страница {page + 1} из {Math.max(1, Math.ceil(d.total / PAGE))}
                  </span>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" disabled={page <= 0} onClick={() => setPage(page - 1)}>
                      Назад
                    </Button>
                    <Button variant="outline" size="sm" disabled={(page + 1) * PAGE >= d.total} onClick={() => setPage(page + 1)}>
                      Вперёд
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}
        </>
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

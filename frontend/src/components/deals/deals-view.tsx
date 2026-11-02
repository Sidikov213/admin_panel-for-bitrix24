"use client";

import { Download, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useManagers, usePipelines } from "@/hooks/queries";
import { api, getApiBase } from "@/lib/api";
import { formatDate, formatDateTime, formatMoney, managerName } from "@/lib/format";

const PAGE_SIZE = 20;

/** URL params set by dashboard KPI links; shown as removable chips. */
const DRILL_PARAMS = ["created_from", "created_to", "closed_from", "closed_to", "outcome", "overdue", "has_future_activity"] as const;

function boolParam(v: string | null): boolean | undefined {
  return v === "true" ? true : v === "false" ? false : undefined;
}

export function DealsView() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const page = Math.max(0, Number(searchParams.get("page") ?? "0"));
  const closedParam = searchParams.get("closed");
  // Legacy link format: ?no_future=1
  const hasFuture = searchParams.get("no_future") === "1" ? false : boolParam(searchParams.get("has_future_activity"));
  const drill = {
    created_from: searchParams.get("created_from") ?? undefined,
    created_to: searchParams.get("created_to") ?? undefined,
    closed_from: searchParams.get("closed_from") ?? undefined,
    closed_to: searchParams.get("closed_to") ?? undefined,
    outcome: searchParams.get("outcome") ?? undefined,
    overdue: boolParam(searchParams.get("overdue")),
    has_future_activity: hasFuture,
  };

  const [search, setSearch] = useState(searchParams.get("search") ?? "");
  // category_id is the Bitrix CATEGORY_ID everywhere (same as the dashboard filter)
  const pipelineId = searchParams.get("category_id") ?? "";
  const stageId = searchParams.get("stage_id") ?? "";
  const managerId = searchParams.get("manager_id") ?? "";
  const status = closedParam === "true" ? "closed" : closedParam === "false" ? "open" : "all";
  const sortBy = searchParams.get("sort_by") ?? "date_modify";
  const sortDir = searchParams.get("sort_dir") ?? "desc";

  const pipelines = usePipelines();
  const managers = useManagers();

  const stages = useMemo(() => {
    if (!pipelineId) return pipelines.data?.flatMap((p) => p.stages) ?? [];
    return pipelines.data?.find((p) => String(p.bitrix_id) === pipelineId)?.stages ?? [];
  }, [pipelineId, pipelines.data]);

  const pushFilters = useCallback(
    (overrides: Record<string, string | number | undefined>) => {
      const params = new URLSearchParams(searchParams.toString());
      params.delete("no_future");
      Object.entries(overrides).forEach(([k, v]) => {
        if (v === undefined || v === "") params.delete(k);
        else params.set(k, String(v));
      });
      router.push(`/deals?${params.toString()}`);
    },
    [router, searchParams],
  );

  // Everything comes from the URL, so the list, the CSV and a shared link always agree
  const filterParams = {
    search: searchParams.get("search") || undefined,
    category_id: pipelineId || undefined,
    stage_id: stageId || undefined,
    manager_id: managerId || undefined,
    closed: status === "closed" ? true : status === "open" ? false : undefined,
    ...drill,
    sort_by: sortBy,
    sort_dir: sortDir,
  };
  const queryParams = { ...filterParams, offset: page * PAGE_SIZE, limit: PAGE_SIZE };

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["deals", queryParams],
    queryFn: () => api.deals(queryParams),
    placeholderData: (prev) => prev,
  });

  const exportQuery = new URLSearchParams();
  for (const [k, v] of Object.entries(filterParams)) {
    if (v !== undefined && v !== "") exportQuery.set(k, String(v));
  }
  const exportHref = `${getApiBase()}/deals/export.csv?${exportQuery.toString()}`;

  const range = (from?: string, to?: string) => `${from ? formatDate(from) : "…"} — ${to ? formatDate(to) : "…"}`;

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const chips: { key: string; label: string; clear: Record<string, undefined> }[] = [];
  if (drill.created_from || drill.created_to) {
    chips.push({
      key: "created",
      label: `Созданы: ${range(drill.created_from, drill.created_to)}`,
      clear: { created_from: undefined, created_to: undefined },
    });
  }
  if (drill.closed_from || drill.closed_to) {
    chips.push({
      key: "closed",
      label: `Закрыты: ${range(drill.closed_from, drill.closed_to)}`,
      clear: { closed_from: undefined, closed_to: undefined },
    });
  }
  if (drill.outcome) {
    chips.push({ key: "outcome", label: drill.outcome === "won" ? "Выиграны" : "Проиграны", clear: { outcome: undefined } });
  }
  if (drill.overdue !== undefined) {
    chips.push({
      key: "overdue",
      label: drill.overdue ? "Есть просроченные дела" : "Без просроченных дел",
      clear: { overdue: undefined },
    });
  }
  if (drill.has_future_activity !== undefined) {
    chips.push({
      key: "future",
      label: drill.has_future_activity ? "Есть следующее дело" : "Нет следующего дела",
      clear: { has_future_activity: undefined },
    });
  }

  if (isLoading && !data) return <PageLoading />;
  if (isError) return <ErrorState message="Не удалось загрузить сделки." onRetry={() => void refetch()} />;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-serif text-3xl font-semibold">Сделки</h1>
          <p className="text-sm text-muted-foreground">Найдено: {total}</p>
        </div>
        <Button asChild variant="outline" size="sm" disabled={!total}>
          <a href={exportHref} download>
            <Download className="mr-2 h-4 w-4" aria-hidden />
            Скачать CSV
          </a>
        </Button>
      </div>

      {chips.length ? (
        <div className="flex flex-wrap items-center gap-2">
          {chips.map((c) => (
            <button
              key={c.key}
              type="button"
              onClick={() => pushFilters({ ...c.clear, page: 0 })}
              className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/5 px-3 py-1 text-sm hover:bg-primary/10"
              aria-label={`Убрать фильтр: ${c.label}`}
            >
              {c.label}
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          ))}
          <button
            type="button"
            className="text-sm text-muted-foreground underline-offset-2 hover:underline"
            onClick={() =>
              pushFilters({ ...Object.fromEntries(DRILL_PARAMS.map((k) => [k, undefined])), page: 0 })
            }
          >
            Сбросить
          </button>
        </div>
      ) : null}

      <div className="grid gap-4 rounded-xl border border-border bg-card p-4 md:grid-cols-2 lg:grid-cols-4">
        <div className="lg:col-span-2">
          <Label className="text-xs text-muted-foreground">Поиск</Label>
          <Input
            placeholder="Название или ID… (Enter)"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && pushFilters({ search, page: 0 })}
          />
        </div>
        <div>
          <Label className="text-xs text-muted-foreground">Воронка</Label>
          <Select
            value={pipelineId || "all"}
            onValueChange={(v) => pushFilters({ category_id: v === "all" ? "" : v, stage_id: "", page: 0 })}
          >
            <SelectTrigger>
              <SelectValue placeholder="Все" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все</SelectItem>
              {pipelines.data?.map((p) => (
                <SelectItem key={p.id} value={String(p.bitrix_id)}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="text-xs text-muted-foreground">Стадия</Label>
          <Select value={stageId || "all"} onValueChange={(v) => pushFilters({ stage_id: v === "all" ? "" : v, page: 0 })}>
            <SelectTrigger>
              <SelectValue placeholder="Все" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все</SelectItem>
              {stages.map((s) => (
                <SelectItem key={s.id} value={String(s.id)}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="text-xs text-muted-foreground">Менеджер</Label>
          <Select
            value={managerId || "all"}
            onValueChange={(v) => pushFilters({ manager_id: v === "all" ? "" : v, page: 0 })}
          >
            <SelectTrigger>
              <SelectValue placeholder="Все" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все</SelectItem>
              {managers.data?.map((m) => (
                <SelectItem key={m.id} value={String(m.id)}>
                  {managerName(m)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="text-xs text-muted-foreground">Статус</Label>
          <Select
            value={status}
            onValueChange={(v) =>
              pushFilters({ closed: v === "closed" ? "true" : v === "open" ? "false" : undefined, page: 0 })
            }
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все</SelectItem>
              <SelectItem value="open">Открытые</SelectItem>
              <SelectItem value="closed">Закрытые</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="text-xs text-muted-foreground">Сортировка</Label>
          <Select
            value={`${sortBy}:${sortDir}`}
            onValueChange={(v) => {
              const [by, dir] = v.split(":");
              pushFilters({ sort_by: by, sort_dir: dir, page: 0 });
            }}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="date_modify:desc">Изменение ↓</SelectItem>
              <SelectItem value="date_modify:asc">Изменение ↑</SelectItem>
              <SelectItem value="date_create:desc">Создание ↓</SelectItem>
              <SelectItem value="title:asc">Название А‑Я</SelectItem>
              <SelectItem value="opportunity:desc">Сумма ↓</SelectItem>
              <SelectItem value="opportunity:asc">Сумма ↑</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {items.length === 0 ? (
        <EmptyState title="Сделки не найдены" description="Измените фильтры или дождитесь синхронизации." />
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Название</TableHead>
                <TableHead>Стадия</TableHead>
                <TableHead>Менеджер</TableHead>
                <TableHead>Сумма</TableHead>
                <TableHead>Изменена</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((deal) => (
                <TableRow key={deal.id}>
                  <TableCell>
                    <Link href={`/deals/${deal.id}`} className="font-medium text-primary hover:underline">
                      {deal.title}
                    </Link>
                  </TableCell>
                  <TableCell>{deal.stage?.name ?? "—"}</TableCell>
                  <TableCell>{managerName(deal.assigned_manager)}</TableCell>
                  <TableCell className="whitespace-nowrap">{formatMoney(deal.opportunity, deal.currency_id ?? "RUB")}</TableCell>
                  <TableCell className="text-muted-foreground">{formatDateTime(deal.date_modify)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">
              Всего: {total} · Страница {page + 1} из {totalPages}
            </span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={page <= 0} onClick={() => pushFilters({ page: page - 1 })}>
                Назад
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={(page + 1) * PAGE_SIZE >= total}
                onClick={() => pushFilters({ page: page + 1 })}
              >
                Вперёд
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

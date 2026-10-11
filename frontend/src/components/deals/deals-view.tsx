"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { DataFreshness } from "@/components/common/data-freshness";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useManagers, usePipelines, useSystem } from "@/hooks/queries";
import { api } from "@/lib/api";
import { formatDateTime, formatMoney, formatNumber, managerName } from "@/lib/format";

const PAGE_SIZE = 40;

export function DealsView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const system = useSystem();

  const page = Math.max(0, Number(searchParams.get("page") ?? "0"));
  const closedParam = searchParams.get("closed");
  const noFuture = searchParams.get("no_future") === "1";

  const [search, setSearch] = useState(searchParams.get("search") ?? "");
  const [pipelineId, setPipelineId] = useState(searchParams.get("category_id") ?? "");
  const [stageId, setStageId] = useState(searchParams.get("stage_id") ?? "");
  const [managerId, setManagerId] = useState(searchParams.get("manager_id") ?? "");
  const [status, setStatus] = useState(closedParam === "true" ? "closed" : closedParam === "false" ? "open" : "all");
  const [sortBy, setSortBy] = useState(searchParams.get("sort_by") ?? "date_modify");
  const [sortDir, setSortDir] = useState(searchParams.get("sort_dir") ?? "desc");

  const pipelines = usePipelines({ analytics: false });
  const managers = useManagers();
  const pipeList = Array.isArray(pipelines.data) ? pipelines.data : [];

  const stages = useMemo(() => {
    if (!pipelineId) return pipeList.flatMap((p) => p.stages);
    return pipeList.find((p) => String(p.id) === pipelineId)?.stages ?? [];
  }, [pipelineId, pipeList]);

  const pushFilters = useCallback(
    (overrides: Record<string, string | number | undefined>) => {
      const params = new URLSearchParams(searchParams.toString());
      Object.entries(overrides).forEach(([k, v]) => {
        if (v === undefined || v === "") params.delete(k);
        else params.set(k, String(v));
      });
      router.push(`/deals?${params.toString()}`);
    },
    [router, searchParams],
  );

  const queryParams = useMemo(() => {
    const closed = status === "closed" ? true : status === "open" ? false : undefined;
    const selectedPipe = pipeList.find((p) => String(p.bitrix_id) === pipelineId || String(p.id) === pipelineId);
    return {
      search: search || undefined,
      category_id: selectedPipe ? Number(selectedPipe.bitrix_id) : pipelineId || undefined,
      stage_id: stageId || undefined,
      manager_id: managerId || undefined,
      closed,
      has_future_activity: noFuture ? false : undefined,
      sort_by: sortBy,
      sort_dir: sortDir,
      offset: page * PAGE_SIZE,
      limit: PAGE_SIZE,
    };
  }, [search, pipelineId, stageId, managerId, status, sortBy, sortDir, page, noFuture, pipeList]);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["deals", queryParams],
    queryFn: () => api.deals(queryParams),
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  if (isLoading) return <PageLoading />;
  if (isError) return <ErrorState message="Не удалось загрузить сделки." onRetry={() => void refetch()} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[13px] text-muted-foreground">
          {formatNumber(total)} сделок
          {noFuture ? " · без следующего дела" : ""}
        </p>
        <DataFreshness freshness={system.data?.freshness} compact />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Input
          className="h-8 w-full max-w-xs text-[13px]"
          placeholder="Поиск…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && pushFilters({ search, page: 0 })}
        />
        <Select
          value={pipelineId || "all"}
          onValueChange={(v) => {
            const id = v === "all" ? "" : v;
            setPipelineId(id);
            setStageId("");
            pushFilters({ category_id: id, stage_id: "", page: 0 });
          }}
        >
          <SelectTrigger className="h-8 w-[9.5rem] text-[13px]">
            <SelectValue placeholder="Воронка" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все воронки</SelectItem>
            {pipeList.map((p) => (
              <SelectItem key={p.id} value={String(p.id)}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={stageId || "all"}
          onValueChange={(v) => {
            const id = v === "all" ? "" : v;
            setStageId(id);
            pushFilters({ stage_id: id, page: 0 });
          }}
        >
          <SelectTrigger className="h-8 w-[9.5rem] text-[13px]">
            <SelectValue placeholder="Этап" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все этапы</SelectItem>
            {stages.map((s) => (
              <SelectItem key={s.id} value={String(s.id)}>
                {s.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={managerId || "all"}
          onValueChange={(v) => {
            const id = v === "all" ? "" : v;
            setManagerId(id);
            pushFilters({ manager_id: id, page: 0 });
          }}
        >
          <SelectTrigger className="h-8 w-[9.5rem] text-[13px]">
            <SelectValue placeholder="Менеджер" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все менеджеры</SelectItem>
            {managers.data?.map((m) => (
              <SelectItem key={m.id} value={String(m.id)}>
                {managerName(m)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={status}
          onValueChange={(v) => {
            setStatus(v);
            const closed = v === "closed" ? "true" : v === "open" ? "false" : undefined;
            pushFilters({ closed, page: 0 });
          }}
        >
          <SelectTrigger className="h-8 w-[8rem] text-[13px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все</SelectItem>
            <SelectItem value="open">Открытые</SelectItem>
            <SelectItem value="closed">Закрытые</SelectItem>
          </SelectContent>
        </Select>
        <Select
          value={`${sortBy}:${sortDir}`}
          onValueChange={(v) => {
            const [by, dir] = v.split(":");
            setSortBy(by);
            setSortDir(dir);
            pushFilters({ sort_by: by, sort_dir: dir });
          }}
        >
          <SelectTrigger className="h-8 w-[10rem] text-[13px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="date_modify:desc">Изменение ↓</SelectItem>
            <SelectItem value="date_modify:asc">Изменение ↑</SelectItem>
            <SelectItem value="title:asc">Название А‑Я</SelectItem>
            <SelectItem value="opportunity:desc">Сумма ↓</SelectItem>
          </SelectContent>
        </Select>
        <Button
          size="sm"
          className="h-8"
          onClick={() =>
            pushFilters({
              search,
              category_id: pipelineId,
              stage_id: stageId,
              manager_id: managerId,
              page: 0,
            })
          }
        >
          Применить
        </Button>
      </div>

      {items.length === 0 ? (
        <EmptyState title="Сделки не найдены" description="Измените фильтры или дождитесь синхронизации." />
      ) : (
        <>
          <div className="panel overflow-hidden">
            <div className="max-h-[calc(100vh-14rem)] overflow-auto">
              <Table className="data-table">
                <TableHeader className="sticky top-0 z-10 bg-card">
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-4">Сделка</TableHead>
                    <TableHead>Этап</TableHead>
                    <TableHead>Менеджер</TableHead>
                    <TableHead className="text-right">Сумма</TableHead>
                    <TableHead className="pr-4">Изменена</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(noFuture ? items.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE) : items).map((deal) => (
                    <TableRow key={deal.id} className="interactive-row">
                      <TableCell className="pl-4">
                        <Link href={`/deals/${deal.id}`} className="font-medium text-foreground hover:text-primary">
                          {deal.title}
                        </Link>
                      </TableCell>
                      <TableCell className="text-muted-foreground">{deal.stage?.name ?? "—"}</TableCell>
                      <TableCell>{managerName(deal.assigned_manager)}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatMoney(deal.opportunity, deal.currency_id ?? "RUB")}
                      </TableCell>
                      <TableCell className="pr-4 text-[12px] text-muted-foreground">
                        {formatDateTime(deal.date_modify)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
          {!noFuture ? (
            <div className="flex items-center justify-between text-[13px]">
              <span className="text-muted-foreground">
                Страница {page + 1} из {totalPages}
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
          ) : null}
        </>
      )}
    </div>
  );
}

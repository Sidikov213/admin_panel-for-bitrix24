"use client";

import { DataFreshness } from "@/components/common/data-freshness";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSystem } from "@/hooks/queries";
import { formatDateTime, formatNumber, syncStateAt } from "@/lib/format";
import { getStatusLabel, getSyncTypeLabel, getWorkerStatusLabel } from "@/lib/ui-labels";

export default function SystemPage() {
  const { data, isLoading, isError, refetch } = useSystem();

  if (isLoading) return <PageLoading rows={3} />;
  if (isError) return <ErrorState message="Не удалось загрузить статус системы." onRetry={() => void refetch()} />;
  if (!data) return <EmptyState title="Нет данных" />;

  return (
    <div className="space-y-6">
      <div>
        <p className="text-[13px] text-muted-foreground">Фоновый процесс, Bitrix (только чтение), курсоры и объёмы данных</p>
      </div>

      <DataFreshness freshness={data.freshness} fallbackAt={data.last_successful_sync} />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Процесс / Bitrix / БД</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>
              Статус фонового процесса:{" "}
              <Badge variant="secondary">{getWorkerStatusLabel(data.worker_status)}</Badge>
            </p>
            <p>
              Bitrix доступен:{" "}
              <Badge variant={data.bitrix_reachable ? "success" : "warning"}>
                {data.bitrix_reachable ? "да" : "нет"}
              </Badge>
            </p>
            <p>
              Bitrix настроен:{" "}
              <Badge variant={data.bitrix_configured ? "success" : "secondary"}>
                {data.bitrix_configured ? "да" : "нет"}
              </Badge>
            </p>
            <p>
              БД:{" "}
              <Badge variant={data.db_ok ? "success" : "warning"}>
                {data.db_ok ? "норма" : "ошибка"}
              </Badge>
            </p>
            <p>Интервал синхронизации: {data.sync_interval_minutes ?? "—"} мин</p>
            <p className="text-muted-foreground">URL webhook не отображается</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Синхронизация</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>Последняя успешная: {formatDateTime(data.last_successful_sync)}</p>
            <p>Последняя попытка: {formatDateTime(data.last_attempted_sync)}</p>
            <p>Курсор сделок: {formatDateTime(syncStateAt(data.deal_cursor ?? data.last_deals_sync))}</p>
            <p>Курсор дел: {formatDateTime(syncStateAt(data.activity_cursor ?? data.last_activities_sync))}</p>
            <p>Полная сверка: {formatDateTime(syncStateAt(data.last_full_reconcile))}</p>
            <p>
              Длительность последней синхронизации:{" "}
              {data.duration_last_sync_seconds != null ? `${Math.round(data.duration_last_sync_seconds)} с` : "—"}
            </p>
            <p>Ошибки за 24 ч: {formatNumber(data.errors_24h ?? 0)}</p>
            <p>Неудачных запусков за 24 ч: {formatNumber(data.failed_runs_24h ?? 0)}</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Объёмы</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>Сделки: {formatNumber(data.totals?.deals)}</p>
            <p>Дела: {formatNumber(data.totals?.activities)}</p>
            <p>Снимки: {formatNumber(data.totals?.snapshots)}</p>
            <p>События изменений: {formatNumber(data.totals?.change_events)}</p>
            {data.category_ids?.length ? <p>Воронки: {data.category_ids.join(", ")}</p> : null}
            {data.bitrix_portal_url ? <p className="text-muted-foreground">Портал: {data.bitrix_portal_url}</p> : null}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Последние запуски синхронизации</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {(data.recent_sync_runs || []).slice(0, 8).map((r) => (
            <div key={r.id} className="flex flex-wrap gap-3 border-b border-slate-100 py-2 last:border-0">
              <Badge variant={r.status === "success" ? "success" : r.status === "failed" ? "destructive" : "secondary"}>
                {getStatusLabel(r.status)}
              </Badge>
              <span>{getSyncTypeLabel(r.sync_type)}</span>
              <span className="text-muted-foreground">{formatDateTime(r.started_at)}</span>
              <span>
                {r.duration_seconds != null ? `${Math.round(r.duration_seconds)} с` : "—"} · ошибок{" "}
                {r.errors_count ?? 0}
              </span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

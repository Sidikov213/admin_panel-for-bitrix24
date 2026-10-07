"use client";

import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSystem } from "@/hooks/queries";
import { formatDateTime, syncStateAt } from "@/lib/format";

export default function SystemPage() {
  const { data, isLoading, isError, refetch } = useSystem();

  if (isLoading) return <PageLoading rows={3} />;
  if (isError) return <ErrorState message="Не удалось загрузить статус системы." onRetry={() => void refetch()} />;
  if (!data) return <EmptyState title="Нет данных" />;

  const stale = Boolean(data.data_may_be_stale || !data.bitrix_reachable);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-serif text-3xl font-semibold">Система</h1>
        <p className="text-sm text-muted-foreground">Интеграции и синхронизация с Bitrix</p>
      </div>

      {stale ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          {data.stale_note ||
            "Данные могут быть устаревшими: Bitrix недоступен или не настроен webhook. Панель работает с последним сохранённым состоянием."}
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Bitrix</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>
              Настроен:{" "}
              <Badge variant={data.bitrix_configured ? "success" : "secondary"}>
                {data.bitrix_configured ? "да" : "нет"}
              </Badge>
            </p>
            <p>
              Доступен:{" "}
              <Badge variant={data.bitrix_reachable ? "success" : "warning"}>
                {data.bitrix_reachable ? "да" : "нет"}
              </Badge>
            </p>
            <p>
              Demo mode:{" "}
              <Badge variant="secondary">{data.demo_mode ? "включён" : "выключен"}</Badge>
            </p>
            {data.bitrix_portal_url ? <p className="text-muted-foreground">Портал: {data.bitrix_portal_url}</p> : null}
            {data.category_ids?.length ? (
              <p className="text-muted-foreground">Воронки: {data.category_ids.join(", ")}</p>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Последняя синхронизация</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>Сделки: {formatDateTime(syncStateAt(data.last_deals_sync))}</p>
            <p>Дела: {formatDateTime(syncStateAt(data.last_activities_sync))}</p>
            <p>Справочники: {formatDateTime(syncStateAt(data.last_dictionaries_sync))}</p>
            {data.latest_sync_run ? (
              <p className="pt-2 text-muted-foreground">
                Запуск #{data.latest_sync_run.id}: {data.latest_sync_run.sync_type} — {data.latest_sync_run.status}
                {data.latest_sync_run.items_processed != null
                  ? ` · обработано ${data.latest_sync_run.items_processed}`
                  : ""}
              </p>
            ) : null}
          </CardContent>
        </Card>
      </div>

      {data.integrations ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Интеграции</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {Object.entries(data.integrations).map(([key, info]) => (
              <p key={key}>
                <span className="font-medium capitalize">{key}</span>: {info.status}
                {info.note ? <span className="text-muted-foreground"> — {info.note}</span> : null}
              </p>
            ))}
          </CardContent>
        </Card>
      ) : null}

      {data.recent_sync_runs?.length ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Недавние запуски sync</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {data.recent_sync_runs.map((r) => (
              <p key={r.id} className="text-muted-foreground">
                #{r.id} {r.sync_type} · {r.status} · {formatDateTime(r.started_at)}
                {r.errors_count ? ` · ошибок ${r.errors_count}` : ""}
              </p>
            ))}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

"use client";

import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDeal } from "@/hooks/queries";
import { bitrixDealUrl } from "@/lib/bitrix-url";
import { formatDateTime, formatMoney, managerName } from "@/lib/format";

export function DealDetailView({ id }: { id: number }) {
  const deal = useDeal(id);

  if (deal.isLoading) return <PageLoading rows={2} />;
  if (deal.isError || !deal.data) {
    return <ErrorState message="Сделка не найдена или ошибка загрузки." onRetry={() => void deal.refetch()} />;
  }

  const d = deal.data;
  const bitrixUrl = d.bitrix_url || bitrixDealUrl(d.bitrix_id);
  const lastChange = d.change_events[0];

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link href="/deals" className="text-sm text-muted-foreground hover:text-foreground">
            ← К списку
          </Link>
          <h1 className="mt-2 font-serif text-3xl font-semibold">{d.title}</h1>
          <div className="mt-2 flex flex-wrap gap-2">
            {d.closed ? <Badge variant="secondary">Закрыта</Badge> : <Badge variant="success">Активна</Badge>}
            {d.no_future_activity_label ? <Badge variant="warning">{d.no_future_activity_label}</Badge> : null}
            {d.hours_without_observed_movement != null ? (
              <Badge variant="outline">Без движения ~{d.hours_without_observed_movement} ч (наблюдаемо)</Badge>
            ) : null}
          </div>
        </div>
        {bitrixUrl ? (
          <Button asChild variant="outline">
            <a href={bitrixUrl} target="_blank" rel="noopener noreferrer">
              Открыть в Bitrix
              <ExternalLink className="ml-2 h-4 w-4" />
            </a>
          </Button>
        ) : (
          <p className="text-xs text-muted-foreground">Укажите BITRIX_PORTAL_URL для ссылки в Bitrix</p>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Основное</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>
              <span className="text-muted-foreground">Bitrix ID:</span> {d.bitrix_id}
            </p>
            <p>
              <span className="text-muted-foreground">Стадия:</span> {d.stage?.name ?? "—"}
            </p>
            <p>
              <span className="text-muted-foreground">Менеджер:</span> {managerName(d.assigned_manager)}
            </p>
            <p>
              <span className="text-muted-foreground">Сумма:</span> {formatMoney(d.opportunity, d.currency_id ?? "RUB")}
            </p>
            <p>
              <span className="text-muted-foreground">Открытых дел:</span> {d.open_activities_count}
            </p>
            <p>
              <span className="text-muted-foreground">Ближайший дедлайн:</span> {formatDateTime(d.next_deadline_at)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Даты</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>
              <span className="text-muted-foreground">Создана:</span> {formatDateTime(d.date_create)}
            </p>
            <p>
              <span className="text-muted-foreground">Изменена (Bitrix):</span> {formatDateTime(d.date_modify)}
            </p>
            <p>
              <span className="text-muted-foreground">Наблюдалась:</span> {formatDateTime(d.observed_at)}
            </p>
            <p>
              <span className="text-muted-foreground">Смена этапа (наблюдаемо):</span>{" "}
              {formatDateTime(d.stage_changed_observed_at)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Последнее наблюдаемое изменение</CardTitle>
            <CardDescription>Время обнаружения при синхронизации</CardDescription>
          </CardHeader>
          <CardContent className="text-sm">
            {!lastChange ? (
              <EmptyState title="Изменений нет" />
            ) : (
              <div className="space-y-1">
                <p className="font-medium">{lastChange.field_name}</p>
                <p className="text-muted-foreground">
                  {lastChange.old_value ?? "—"} → {lastChange.new_value ?? "—"}
                </p>
                <p className="text-xs text-muted-foreground">{formatDateTime(lastChange.observed_at)}</p>
                {lastChange.note ? <p className="text-xs text-amber-800">{lastChange.note}</p> : null}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Связанные дела</CardTitle>
        </CardHeader>
        <CardContent>
          {!d.activities.length ? (
            <EmptyState title="Дела не найдены" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Тема</TableHead>
                  <TableHead>Дедлайн</TableHead>
                  <TableHead>Статус</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.activities.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell>{a.subject || `Дело #${a.bitrix_id}`}</TableCell>
                    <TableCell>{formatDateTime(a.deadline)}</TableCell>
                    <TableCell>{a.completed ? "Завершено" : "Открыто"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Наблюдаемая история</CardTitle>
          <CardDescription>
            Polling не гарантирует обнаружение каждого промежуточного изменения
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!d.change_events.length ? (
            <EmptyState title="История пуста" />
          ) : (
            <ul className="divide-y divide-border">
              {d.change_events.map((c) => (
                <li key={c.id ?? `${c.field_name}-${c.observed_at}`} className="py-3 text-sm">
                  <p className="font-medium">{c.field_name}</p>
                  <p className="text-muted-foreground">
                    {c.old_value ?? "—"} → {c.new_value ?? "—"}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Обнаружено: {formatDateTime(c.observed_at)}
                    {c.bitrix_event_at ? ` · Bitrix: ${formatDateTime(c.bitrix_event_at)}` : ""}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

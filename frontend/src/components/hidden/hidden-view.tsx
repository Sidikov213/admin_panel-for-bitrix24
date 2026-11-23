"use client";

import { Undo2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { useAuth } from "@/components/providers/auth-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useExcludedDeals, useHiddenActions, useHiddenManagers, useManagers } from "@/hooks/queries";
import { formatDateTime, formatMoney, managerName } from "@/lib/format";

/** Everything taken out of sight in the panel, in one place, with the way back. */
export function HiddenView() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const deals = useExcludedDeals();
  const hidden = useHiddenManagers();
  const shown = useManagers();
  const { restoreDeal, setManagerTracked } = useHiddenActions();
  const [toHide, setToHide] = useState("");

  const busy = restoreDeal.isPending || setManagerTracked.isPending;
  const failed = restoreDeal.isError || setManagerTracked.isError;
  const dealItems = deals.data?.items ?? [];
  const dealTotal = deals.data?.total ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-serif text-3xl font-semibold tracking-tight">Скрытое</h1>
        <p className="text-sm text-muted-foreground">
          Сделки, которые не учитываются в аналитике, и сотрудники, которых нет в списках менеджеров. В Bitrix ничего
          не меняется.
        </p>
      </div>

      {failed ? <p className="text-sm text-destructive">Не удалось сохранить. Попробуйте ещё раз.</p> : null}

      <Card>
        <CardHeader>
          <CardTitle className="font-serif text-base">Сделки вне аналитики{deals.data ? ` · ${dealTotal}` : ""}</CardTitle>
          <CardDescription>
            Их нет в дашборде, отчётах, просрочках и списках. Чтобы убрать сделку, откройте её и нажмите «Не учитывать
            в аналитике».
          </CardDescription>
        </CardHeader>
        <CardContent>
          {deals.isLoading ? (
            <PageLoading rows={2} />
          ) : deals.isError ? (
            <ErrorState message="Не удалось загрузить сделки" onRetry={() => void deals.refetch()} />
          ) : dealItems.length === 0 ? (
            <EmptyState title="Скрытых сделок нет" />
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
                    {isAdmin ? <TableHead /> : null}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {dealItems.map((deal) => (
                    <TableRow key={deal.id}>
                      <TableCell>
                        <Link href={`/deals/${deal.id}`} className="font-medium text-primary hover:underline">
                          №{deal.bitrix_id} {deal.title}
                        </Link>
                      </TableCell>
                      <TableCell>{deal.stage?.name ?? "—"}</TableCell>
                      <TableCell>{managerName(deal.assigned_manager)}</TableCell>
                      <TableCell className="whitespace-nowrap">
                        {formatMoney(deal.opportunity, deal.currency_id ?? "RUB")}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {formatDateTime(deal.date_modify)}
                      </TableCell>
                      {isAdmin ? (
                        <TableCell className="text-right">
                          <Button variant="outline" size="sm" disabled={busy} onClick={() => restoreDeal.mutate(deal.id)}>
                            <Undo2 className="mr-2 h-4 w-4" />
                            Вернуть
                          </Button>
                        </TableCell>
                      ) : null}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {dealTotal > dealItems.length ? (
                <p className="pt-3 text-xs text-muted-foreground">
                  Показаны последние {dealItems.length} из {dealTotal}. Остальные — в списке сделок со статусом
                  «Исключённые из аналитики».
                </p>
              ) : null}
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="font-serif text-base">
            Скрытые менеджеры{hidden.data ? ` · ${hidden.data.length}` : ""}
          </CardTitle>
          <CardDescription>
            Их нет в списках менеджеров и в отчётах по людям, но их сделки по-прежнему входят в общие цифры. Здесь
            только те, у кого есть сделки.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {isAdmin && shown.data && shown.data.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              <select
                aria-label="Кого скрыть"
                className="h-10 rounded-lg border border-input bg-background px-3 text-sm"
                value={toHide}
                onChange={(e) => setToHide(e.target.value)}
              >
                <option value="">Скрыть менеджера из списков…</option>
                {shown.data.map((m) => (
                  <option key={m.id} value={m.id}>
                    {managerName(m)}
                  </option>
                ))}
              </select>
              <Button
                variant="outline"
                disabled={!toHide || busy}
                onClick={() => {
                  setManagerTracked.mutate({ id: Number(toHide), tracked: false });
                  setToHide("");
                }}
              >
                Скрыть
              </Button>
            </div>
          ) : null}

          {hidden.isLoading ? (
            <PageLoading rows={2} />
          ) : hidden.isError ? (
            <ErrorState message="Не удалось загрузить список" onRetry={() => void hidden.refetch()} />
          ) : (hidden.data ?? []).length === 0 ? (
            <EmptyState title="Скрытых менеджеров нет" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Сотрудник</TableHead>
                  <TableHead>Активных сделок</TableHead>
                  <TableHead>Всего сделок</TableHead>
                  <TableHead>В Bitrix</TableHead>
                  {isAdmin ? <TableHead /> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {(hidden.data ?? []).map((m) => (
                  <TableRow key={m.id}>
                    <TableCell>
                      <Link href={`/managers/${m.id}`} className="font-medium text-primary hover:underline">
                        {managerName(m)}
                      </Link>
                    </TableCell>
                    <TableCell>{m.active_deals_count}</TableCell>
                    <TableCell>{m.deals_count}</TableCell>
                    <TableCell className="text-muted-foreground">{m.is_active === false ? "уволен" : "работает"}</TableCell>
                    {isAdmin ? (
                      <TableCell className="text-right">
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={busy}
                          onClick={() => setManagerTracked.mutate({ id: m.id, tracked: true })}
                        >
                          <Undo2 className="mr-2 h-4 w-4" />
                          Вернуть в списки
                        </Button>
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

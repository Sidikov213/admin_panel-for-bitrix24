"use client";

import Link from "next/link";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useStalled } from "@/hooks/queries";
import { formatDateTime } from "@/lib/format";

const NO_FUTURE_LABEL = "нет следующего запланированного дела";

export function StalledView() {
  const noFuture = useStalled("no_future");
  const rules = useStalled("rules");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-serif text-3xl font-semibold">Сделки без движения</h1>
        <p className="text-sm text-muted-foreground">
          Основной список — проверяемый факт ({NO_FUTURE_LABEL}). Это не SLA и не «нарушители регламента».
        </p>
      </div>

      <Tabs defaultValue="no-future">
        <TabsList>
          <TabsTrigger value="no-future">{NO_FUTURE_LABEL}</TabsTrigger>
          <TabsTrigger value="stalled-rules">Предварительные правила (не SLA)</TabsTrigger>
        </TabsList>

        <TabsContent value="no-future">
          {noFuture.isLoading ? (
            <PageLoading rows={2} />
          ) : noFuture.isError ? (
            <ErrorState message="Не удалось загрузить сделки." onRetry={() => void noFuture.refetch()} />
          ) : !noFuture.data?.items.length ? (
            <EmptyState title="Все активные сделки имеют следующее дело" description="Или данных нет в CRM." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Сделка</TableHead>
                  <TableHead>Менеджер</TableHead>
                  <TableHead>Без движения</TableHead>
                  <TableHead>Последняя активность</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {noFuture.data.items.map((d) => (
                  <TableRow key={d.deal_id}>
                    <TableCell>
                      <Link href={`/deals/${d.deal_id}`} className="font-medium text-primary hover:underline">
                        {d.title}
                      </Link>
                      <Badge variant="warning" className="ml-2">
                        {NO_FUTURE_LABEL}
                      </Badge>
                    </TableCell>
                    <TableCell>{d.manager ?? "—"}</TableCell>
                    <TableCell>
                      {d.hours_without_observed_movement != null
                        ? `~${d.hours_without_observed_movement} ч`
                        : "—"}
                    </TableCell>
                    <TableCell>{formatDateTime(d.last_observed_activity_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </TabsContent>

        <TabsContent value="stalled-rules">
          {rules.data?.rules_config ? (
            <p className="mb-3 text-xs text-muted-foreground">{rules.data.rules_config.note}</p>
          ) : null}
          {rules.isLoading ? (
            <PageLoading rows={2} />
          ) : rules.isError ? (
            <ErrorState message="Не удалось загрузить правила." onRetry={() => void rules.refetch()} />
          ) : rules.data?.enabled === false ? (
            <EmptyState
              title="Регламент ещё не настроен"
              description="Правила застоя отключены до утверждения отделом продаж. Используйте вкладку «нет следующего запланированного дела»."
            />
          ) : !rules.data?.items.length ? (
            <EmptyState title="По предварительным правилам записей нет" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Сделка</TableHead>
                  <TableHead>Причина (наблюдаемо)</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rules.data.items.map((d) => (
                  <TableRow key={d.deal_id}>
                    <TableCell>
                      <Link href={`/deals/${d.deal_id}`} className="font-medium text-primary hover:underline">
                        {d.title}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{d.reason ?? "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

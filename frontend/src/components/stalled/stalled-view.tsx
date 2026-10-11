"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { DataFreshness } from "@/components/common/data-freshness";
import { ErrorState, PageLoading } from "@/components/common/page-states";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useStalled, useStalledRules, useSystem } from "@/hooks/queries";
import { formatMoney, formatNumber } from "@/lib/format";

export function StalledView() {
  const search = useSearchParams();
  const initial = (search.get("mode") as "no_future" | "rules") || "no_future";
  const noFuture = useStalled("no_future");
  const rules = useStalled("rules");
  const rulesAdmin = useStalledRules();
  const system = useSystem();

  if (noFuture.isLoading) return <PageLoading rows={8} />;
  if (noFuture.isError)
    return <ErrorState message="Не удалось загрузить сделки." onRetry={() => void noFuture.refetch()} />;

  const data = noFuture.data;
  const items = data?.items ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[13px] text-muted-foreground">
          {data?.summary_label ||
            `${formatNumber(data?.total ?? 0)} сделок · ${formatMoney(data?.sum_opportunity)} без следующего действия`}
        </p>
        <DataFreshness freshness={system.data?.freshness} compact />
      </div>

      <Tabs defaultValue={initial}>
        <TabsList>
          <TabsTrigger value="no_future">Нет следующего дела</TabsTrigger>
          <TabsTrigger value="rules">Правила (черновик)</TabsTrigger>
        </TabsList>
        <TabsContent value="no_future" className="mt-4 space-y-4">
          <div className="panel overflow-x-auto">
            <div className="max-h-[calc(100vh-14rem)] overflow-auto">
              <Table className="data-table">
                <TableHeader className="sticky top-0 z-10 bg-card">
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-4">Сделка</TableHead>
                    <TableHead>Менеджер</TableHead>
                    <TableHead>Этап</TableHead>
                    <TableHead className="text-right">Сумма</TableHead>
                    <TableHead>Проблема</TableHead>
                    <TableHead className="pr-4 font-semibold text-foreground">Длительность</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((d) => (
                    <TableRow key={d.deal_id} className="interactive-row">
                      <TableCell className="pl-4">
                        <Link href={`/deals/${d.deal_id}`} className="font-medium hover:text-primary">
                          {d.title}
                        </Link>
                        {d.bitrix_url ? (
                          <>
                            {" · "}
                            <a href={d.bitrix_url} target="_blank" rel="noreferrer" className="text-[12px] text-primary">
                              Bitrix
                            </a>
                          </>
                        ) : null}
                      </TableCell>
                      <TableCell>{d.manager || "—"}</TableCell>
                      <TableCell className="text-muted-foreground">{d.stage || "—"}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatMoney(d.amount)}</TableCell>
                      <TableCell className="text-[13px]">Нет следующего дела</TableCell>
                      <TableCell className="pr-4 font-semibold tabular-nums text-[var(--warning)]">
                        {d.time_without_future_task || "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        </TabsContent>
        <TabsContent value="rules" className="mt-4">
          <div className="panel panel-pad space-y-3 text-[13px]">
            <div className="flex items-center gap-2">
              <h2 className="section-title">Движок правил</h2>
              <Badge variant="secondary">{rules.data?.enabled ? "включён" : "выключен"}</Badge>
            </div>
            <p className="text-muted-foreground">{rules.data?.rules_config?.note || rules.data?.disclaimer}</p>
            <p className="text-muted-foreground">
              Черновиков: {rulesAdmin.data?.total ?? 0}.{" "}
              <Link href="/admin/sales-rules" className="font-medium text-primary hover:underline">
                Открыть регламент
              </Link>
            </p>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}

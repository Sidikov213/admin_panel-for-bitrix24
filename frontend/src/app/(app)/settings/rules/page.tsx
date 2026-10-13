"use client";

import Link from "next/link";
import { ErrorState, PageLoading } from "@/components/common/page-states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useStalledRules } from "@/hooks/queries";
import { getEnabledLabel } from "@/lib/ui-labels";

export default function StalledRulesSettingsPage() {
  const q = useStalledRules();

  if (q.isLoading) return <PageLoading rows={4} />;
  if (q.isError) return <ErrorState message="Не удалось загрузить правила." onRetry={() => void q.refetch()} />;

  const data = q.data;

  return (
    <div className="space-y-6">
      <div>
        <Link href="/stalled" className="text-sm text-muted-foreground hover:text-foreground">
          ← К разделу «Без следующего дела»
        </Link>
        <h1 className="page-title mt-2 text-[1.5rem]">Правила зависших сделок</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Конфигурируемый механизм готов · значения порогов не применяются до утверждения регламента
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            Статус движка
            <Badge variant="secondary">{data?.rules_applied ? "применяется" : "только факты"}</Badge>
          </CardTitle>
          <CardDescription>{data?.note}</CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          В правиле задаются: воронка, этап, макс. простой (мин), требование следующего дела, макс.
          до следующего дела, календарь, статус сделки, включено/выключено. Сейчас UI показывает
          черновики; включение на API принудительно выключено.
        </CardContent>
      </Card>

      <div className="overflow-x-auto rounded-xl border bg-white">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead>Название</TableHead>
              <TableHead>Воронка</TableHead>
              <TableHead>Этап</TableHead>
              <TableHead>Макс. простой, мин</TableHead>
              <TableHead>След. дело обязательно</TableHead>
              <TableHead>Статус</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data?.items ?? []).length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-muted-foreground">
                  Правил пока нет — показывать только объективные факты.
                </TableCell>
              </TableRow>
            ) : (
              data!.items.map((r) => (
                <TableRow key={String(r.id)}>
                  <TableCell>{String(r.id)}</TableCell>
                  <TableCell>{String(r.name || "—")}</TableCell>
                  <TableCell>{String(r.pipeline_bitrix_id ?? "любая")}</TableCell>
                  <TableCell>{String(r.stage_id ?? "любой")}</TableCell>
                  <TableCell>{String(r.max_idle_minutes ?? "—")}</TableCell>
                  <TableCell>
                    {r.future_activity_required === true
                      ? "да"
                      : r.future_activity_required === false
                        ? "нет"
                        : "—"}
                  </TableCell>
                  <TableCell>{getEnabledLabel(Boolean(r.enabled))}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

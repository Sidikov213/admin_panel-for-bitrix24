"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useManager } from "@/hooks/queries";
import { formatDateTime, formatMoney, formatNumber, managerName } from "@/lib/format";

export default function ManagerDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const manager = useManager(id);

  if (manager.isLoading) return <PageLoading />;
  if (manager.isError || !manager.data) {
    return <ErrorState message="Менеджер не найден." onRetry={() => void manager.refetch()} />;
  }

  const { manager: m, kpis, deals } = manager.data;

  return (
    <div className="space-y-6">
      <Link href="/managers" className="text-sm text-muted-foreground hover:text-foreground">
        ← Менеджеры
      </Link>
      <h1 className="font-serif text-3xl font-semibold">{managerName(m)}</h1>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">Активные</CardTitle>
          </CardHeader>
          <CardContent className="font-serif text-2xl font-semibold">{formatNumber(kpis.active_deals_count)}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">Новые</CardTitle>
          </CardHeader>
          <CardContent className="font-serif text-2xl font-semibold">{formatNumber(kpis.new_deals_count)}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">Успешно закрыто</CardTitle>
          </CardHeader>
          <CardContent className="font-serif text-2xl font-semibold">{formatNumber(kpis.won_count)}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">Без следующего дела</CardTitle>
          </CardHeader>
          <CardContent className="font-serif text-2xl font-semibold">
            {formatNumber(kpis.deals_without_future_activity_count)}
          </CardContent>
        </Card>
      </div>

      <div>
        <h2 className="mb-3 font-serif text-xl font-semibold">Сделки менеджера</h2>
        {!deals.length ? (
          <EmptyState title="Нет сделок" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Сделка</TableHead>
                <TableHead>Этап</TableHead>
                <TableHead>Сумма</TableHead>
                <TableHead>Флаг</TableHead>
                <TableHead>Изменена</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {deals.map((d) => (
                <TableRow key={d.id}>
                  <TableCell>
                    <Link href={`/deals/${d.id}`} className="text-primary hover:underline">
                      {d.title}
                    </Link>
                  </TableCell>
                  <TableCell>{d.stage_name ?? "—"}</TableCell>
                  <TableCell>{formatMoney(d.opportunity)}</TableCell>
                  <TableCell>
                    {!d.has_future_activity && !d.closed ? (
                      <Badge variant="warning">нет следующего дела</Badge>
                    ) : d.closed ? (
                      <Badge variant="secondary">закрыта</Badge>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{formatDateTime(d.date_modify)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}

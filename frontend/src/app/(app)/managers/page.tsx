"use client";

import Link from "next/link";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useManagers } from "@/hooks/queries";
import { formatMoney, formatNumber, managerName } from "@/lib/format";

export default function ManagersPage() {
  const { data, isLoading, isError, refetch } = useManagers();

  if (isLoading) return <PageLoading />;
  if (isError) return <ErrorState message="Не удалось загрузить менеджеров." onRetry={() => void refetch()} />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-serif text-3xl font-semibold">Менеджеры</h1>
        <p className="text-sm text-muted-foreground">Показатели за последние 30 дней · без искусственного рейтинга</p>
      </div>
      {!data?.length ? (
        <EmptyState title="Менеджеры не найдены" />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ФИО</TableHead>
              <TableHead>Активные</TableHead>
              <TableHead>Новые</TableHead>
              <TableHead>Закрыто</TableHead>
              <TableHead>Сумма в работе</TableHead>
              <TableHead>Без след. дела</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.map((m) => (
              <TableRow key={m.id}>
                <TableCell>
                  <Link href={`/managers/${m.id}`} className="font-medium text-primary hover:underline">
                    {managerName(m)}
                  </Link>
                </TableCell>
                <TableCell>{formatNumber(m.active_deals_count ?? 0)}</TableCell>
                <TableCell>{formatNumber(m.new_deals_count ?? 0)}</TableCell>
                <TableCell>{formatNumber(m.won_count ?? 0)}</TableCell>
                <TableCell>{formatMoney(m.sum_active_opportunity ?? 0)}</TableCell>
                <TableCell>{formatNumber(m.deals_without_future_activity_count ?? 0)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

"use client";

import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useOverdue } from "@/hooks/queries";
import { formatDateTime } from "@/lib/format";

export default function OverduePage() {
  const { data, isLoading, isError, refetch } = useOverdue();

  if (isLoading) return <PageLoading />;
  if (isError) return <ErrorState message="Не удалось загрузить просроченные дела." onRetry={() => void refetch()} />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-serif text-3xl font-semibold">Просроченные дела</h1>
        <p className="text-sm text-muted-foreground">Незавершённые активности с дедлайном в прошлом</p>
      </div>
      {!data?.items.length ? (
        <EmptyState title="Просроченных дел нет" />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Тема</TableHead>
              <TableHead>Дедлайн</TableHead>
              <TableHead>Owner ID</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.map((a) => (
              <TableRow key={a.id}>
                <TableCell>{a.subject}</TableCell>
                <TableCell>{formatDateTime(a.deadline)}</TableCell>
                <TableCell className="text-muted-foreground">{a.owner_id ?? "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

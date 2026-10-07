"use client";

import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { usePipelines } from "@/hooks/queries";

export default function PipelinesPage() {
  const { data, isLoading, isError, refetch } = usePipelines();

  if (isLoading) return <PageLoading />;
  if (isError) return <ErrorState message="Не удалось загрузить воронки." onRetry={() => void refetch()} />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-serif text-3xl font-semibold">Воронки</h1>
        <p className="text-sm text-muted-foreground">Справочник стадий из Bitrix</p>
      </div>
      {!data?.length ? (
        <EmptyState title="Воронки не синхронизированы" />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {data.map((p) => (
            <Card key={p.id}>
              <CardHeader>
                <CardTitle>{p.name}</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2">
                  {p.stages
                    .slice()
                    .sort((a, b) => a.sort - b.sort)
                    .map((s) => (
                      <li key={s.id} className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2 text-sm">
                        <span>{s.name}</span>
                        {s.semantics ? <Badge variant="secondary">{s.semantics}</Badge> : null}
                      </li>
                    ))}
                </ul>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

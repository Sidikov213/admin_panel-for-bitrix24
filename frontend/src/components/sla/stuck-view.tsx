"use client";

import Link from "next/link";
import { useState } from "react";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { BitrixLink, ScopeFilters } from "@/components/common/scope-filters";
import { useAuth } from "@/components/providers/auth-provider";
import { SlaRulesCard } from "@/components/sla/sla-rules-card";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useStuck } from "@/hooks/queries";
import { formatDateTime, formatDuration, formatMoney, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { StuckDeal } from "@/types/api";

const isWork = (d: StuckDeal) => d.unit !== "calendar_days";

export function StuckView() {
  const { user } = useAuth();
  const [categoryId, setCategoryId] = useState<number | undefined>();
  const [managerId, setManagerId] = useState<number | undefined>();
  const [onlyStuck, setOnlyStuck] = useState(true);
  const q = useStuck({ category_id: categoryId, manager_id: managerId, only_stuck: onlyStuck });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-serif text-3xl font-semibold">Зависшие сделки</h1>
        <p className="text-sm text-muted-foreground">
          Сделки, которые находятся на стадии дольше установленного срока. Часовые сроки считаются в рабочем времени.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <ScopeFilters idPrefix="stuck" categoryId={categoryId} managerId={managerId} onCategory={setCategoryId} onManager={setManagerId} />
        <label className="flex h-10 items-center gap-2 text-sm">
          <input type="checkbox" checked={onlyStuck} onChange={(e) => setOnlyStuck(e.target.checked)} />
          Только зависшие
        </label>
      </div>

      {q.isLoading && !q.data ? (
        <PageLoading rows={3} />
      ) : q.isError ? (
        <ErrorState message="Не удалось загрузить зависшие сделки." onRetry={() => void q.refetch()} />
      ) : q.data ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">Зависло</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="font-serif text-3xl font-semibold">{q.data.stuck_total}</p>
                <p className="text-xs text-muted-foreground">
                  из {q.data.open_total} открытых ·{" "}
                  {formatPercent(q.data.open_total ? (q.data.stuck_total / q.data.open_total) * 100 : null)}
                </p>
              </CardContent>
            </Card>
            {q.data.by_stage
              .filter((s) => s.tracked && s.stuck)
              .slice(0, 3)
              .map((s) => (
                <Card key={s.stage_id}>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium text-muted-foreground">{s.name}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="font-serif text-3xl font-semibold">{s.stuck}</p>
                    <p className="text-xs text-muted-foreground">
                      из {s.open} · срок {s.rule}
                    </p>
                  </CardContent>
                </Card>
              ))}
          </div>

          {!q.data.items.length ? (
            <EmptyState title={onlyStuck ? "Зависших сделок нет" : "Открытых сделок нет"} />
          ) : (
            <Card>
              <CardContent className="pt-6">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Сделка</TableHead>
                      <TableHead>Стадия</TableHead>
                      <TableHead>На стадии</TableHead>
                      <TableHead>Последнее действие</TableHead>
                      <TableHead>Следующее дело</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {q.data.items.map((d) => (
                      <TableRow key={d.deal_id}>
                        <TableCell>
                          <Link href={`/deals/${d.deal_id}`} className="font-medium text-primary hover:underline">
                            №{d.bitrix_id} {d.title}
                          </Link>
                          <p className="text-xs text-muted-foreground">
                            {[d.manager, d.opportunity ? formatMoney(d.opportunity) : null].filter(Boolean).join(" · ")}
                          </p>
                          <BitrixLink href={d.bitrix_url} />
                        </TableCell>
                        <TableCell>
                          {d.stage}
                          <p className="text-xs text-muted-foreground">{d.pipeline}</p>
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          <span className={cn(d.stuck && "font-semibold text-red-700")}>
                            {formatDuration(d.in_stage_seconds, { work: isWork(d) })}
                          </span>
                          <p className="text-xs text-muted-foreground">
                            срок {d.rule}
                            {d.in_stage_since_source !== "bitrix" ? " · приблизительно" : ""}
                          </p>
                        </TableCell>
                        <TableCell>
                          {d.last_activity ? (
                            <>
                              {d.last_activity.type}
                              {d.last_activity.subject ? `: ${d.last_activity.subject}` : ""}
                              <p className="text-xs text-muted-foreground">{formatDateTime(d.last_activity.at)}</p>
                            </>
                          ) : (
                            <span className="text-muted-foreground">дел нет</span>
                          )}
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          {d.has_future_activity && d.next_deadline_at ? (
                            formatDateTime(d.next_deadline_at)
                          ) : (
                            <Badge variant="warning">не назначено</Badge>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}

          {q.data.by_manager.length && managerId === undefined ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">По менеджерам</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Менеджер</TableHead>
                      <TableHead>Открытых</TableHead>
                      <TableHead>Зависло</TableHead>
                      <TableHead>Доля</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {q.data.by_manager.map((m) => (
                      <TableRow key={m.manager_id}>
                        <TableCell>{m.name ?? `#${m.manager_id}`}</TableCell>
                        <TableCell>{m.open}</TableCell>
                        <TableCell>{m.stuck}</TableCell>
                        <TableCell>{formatPercent(m.share)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          ) : null}
        </>
      ) : null}

      <SlaRulesCard editable={user?.role === "admin"} />
    </div>
  );
}

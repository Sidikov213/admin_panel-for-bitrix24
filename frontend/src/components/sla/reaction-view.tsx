"use client";

import Link from "next/link";
import { useState } from "react";
import { PeriodPicker, defaultPeriod, type PeriodValue } from "@/components/common/period-picker";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { BitrixLink, ScopeFilters } from "@/components/common/scope-filters";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useReaction } from "@/hooks/queries";
import { formatDateTime, formatDuration, formatPercent } from "@/lib/format";

const work = { work: true };

export function ReactionView() {
  const [period, setPeriod] = useState<PeriodValue>(defaultPeriod);
  const [categoryId, setCategoryId] = useState<number | undefined>();
  const [managerId, setManagerId] = useState<number | undefined>();
  const q = useReaction({ period_start: period.from, period_end: period.to, category_id: categoryId, manager_id: managerId });
  const d = q.data;
  const norm = d ? Object.values(d.norms)[0] : undefined;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-serif text-3xl font-semibold">Скорость реакции</h1>
        <p className="text-sm text-muted-foreground">
          Как быстро менеджеры берут новые заявки в работу и выходят на первый контакт. Время — рабочее.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <PeriodPicker value={period} onChange={setPeriod} />
        <ScopeFilters idPrefix="reaction" categoryId={categoryId} managerId={managerId} onCategory={setCategoryId} onManager={setManagerId} />
      </div>

      {q.isLoading && !d ? (
        <PageLoading rows={3} />
      ) : q.isError ? (
        <ErrorState message="Не удалось посчитать скорость реакции." onRetry={() => void q.refetch()} />
      ) : d ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Stat title="Взятие в работу" value={formatDuration(d.summary.take.median_seconds, work)} hint={norm ? `медиана · норма ${formatDuration(norm.take, work)}` : "медиана"} />
            <Stat title="Первый контакт" value={formatDuration(d.summary.contact.median_seconds, work)} hint={norm ? `медиана · норма ${formatDuration(norm.contact, work)}` : "медиана"} />
            <Stat title="Дольше нормы" value={formatPercent(d.summary.late_share)} hint={`${d.summary.late} из ${d.summary.deals} заявок`} />
            <Stat title="Ждут контакта сейчас" value={String(d.summary.waiting)} hint={`из них дольше нормы: ${d.summary.waiting_late}`} />
          </div>
          {d.skipped_without_history ? (
            <p className="text-xs text-muted-foreground">
              {d.skipped_without_history} сделок без истории переходов не учтены: по ним неизвестно, когда они ушли со стадии.
            </p>
          ) : null}

          {!d.summary.deals ? (
            <EmptyState title="За период новых заявок нет" />
          ) : (
            <>
              {d.managers.length ? (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">По менеджерам</CardTitle>
                    <CardDescription>{d.definitions.contact}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Менеджер</TableHead>
                          <TableHead>Заявок</TableHead>
                          <TableHead>Взятие (медиана)</TableHead>
                          <TableHead>Контакт (медиана)</TableHead>
                          <TableHead>Дольше нормы</TableHead>
                          <TableHead>Ждут сейчас</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {d.managers.map((m) => (
                          <TableRow key={m.manager_id}>
                            <TableCell>{m.name ?? `#${m.manager_id}`}</TableCell>
                            <TableCell>{m.deals}</TableCell>
                            <TableCell>{formatDuration(m.take.median_seconds, work)}</TableCell>
                            <TableCell>{formatDuration(m.contact.median_seconds, work)}</TableCell>
                            <TableCell>
                              {m.late} · {formatPercent(m.late_share)}
                            </TableCell>
                            <TableCell>{m.waiting}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              ) : null}

              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Самая долгая реакция</CardTitle>
                  <CardDescription>{d.definitions.late}</CardDescription>
                </CardHeader>
                <CardContent>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Сделка</TableHead>
                        <TableHead>Создана</TableHead>
                        <TableHead>Взятие</TableHead>
                        <TableHead>Контакт</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {d.worst.map((r) => (
                        <TableRow key={r.deal_id}>
                          <TableCell>
                            <Link href={`/deals/${r.deal_id}`} className="font-medium text-primary hover:underline">
                              №{r.bitrix_id} {r.title}
                            </Link>
                            <p className="text-xs text-muted-foreground">{[r.manager, r.stage].filter(Boolean).join(" · ")}</p>
                            <BitrixLink href={r.bitrix_url} />
                          </TableCell>
                          <TableCell className="whitespace-nowrap">{formatDateTime(r.created_at)}</TableCell>
                          <TableCell className="whitespace-nowrap">{formatDuration(r.take_seconds, work)}</TableCell>
                          <TableCell className="whitespace-nowrap">
                            {r.contact_seconds !== null ? (
                              <span className={r.late ? "font-semibold text-red-700" : undefined}>
                                {formatDuration(r.contact_seconds, work)}
                              </span>
                            ) : (
                              <Badge variant={r.late ? "destructive" : "secondary"}>
                                ждёт {formatDuration(r.waiting_seconds, work)}
                              </Badge>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            </>
          )}
        </>
      ) : null}
    </div>
  );
}

function Stat({ title, value, hint }: { title: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="font-serif text-2xl font-semibold">{value}</p>
        {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}

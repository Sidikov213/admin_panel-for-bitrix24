"use client";

import Link from "next/link";
import { useState } from "react";
import { PeriodPicker, defaultPeriod, type PeriodValue } from "@/components/common/period-picker";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { BitrixLink, selectClass } from "@/components/common/scope-filters";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAvitoChat, useAvitoStatus, useAvitoSummary } from "@/hooks/queries";
import { formatDateTime, formatDuration, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AvitoChatRow } from "@/types/api";

const work = { work: true };

export function AvitoView() {
  const status = useAvitoStatus();
  const [period, setPeriod] = useState<PeriodValue>(defaultPeriod);
  const [accountId, setAccountId] = useState<number | undefined>();
  const [openChat, setOpenChat] = useState<string | null>(null);
  const q = useAvitoSummary({ period_start: period.from, period_end: period.to, account_id: accountId });
  const st = status.data;
  const d = q.data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-serif text-3xl font-semibold">Avito</h1>
        <p className="text-sm text-muted-foreground">
          Обращения из Авито: скорость первого ответа (в рабочем времени), диалоги без ответа, объявления и связь со сделками
          Bitrix. Только чтение — панель ничего не отправляет от имени аккаунтов.
        </p>
      </div>

      {st && !st.configured ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Avito не подключён</CardTitle>
            <CardDescription>
              {st.config_error ? `Ошибка в настройке: ${st.config_error}. ` : null}
              Для каждого аккаунта нужны Client ID и Client Secret из раздела «Для профессионалов → API». Их задают в .env
              сервера (переменная AVITO_ACCOUNTS), в панели секреты не хранятся.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      {st?.accounts.length ? (
        <div className="grid gap-3 sm:grid-cols-3">
          {st.accounts.map((a) => (
            <div key={a.id} className="rounded-lg border border-border p-3 text-sm">
              <p className="font-medium">{a.name}</p>
              <p className="text-xs text-muted-foreground">id {a.id}</p>
              {a.last_error ? (
                <p className="mt-1 text-xs text-red-700">{a.last_error}</p>
              ) : (
                <p className="mt-1 text-xs text-muted-foreground">
                  {a.last_sync_at ? `обновлено ${formatDateTime(a.last_sync_at)}` : "ещё не загружался"}
                </p>
              )}
            </div>
          ))}
        </div>
      ) : null}

      <div className="flex flex-wrap items-end gap-3">
        <PeriodPicker value={period} onChange={setPeriod} />
        {st && st.accounts.length > 1 ? (
          <div className="w-full space-y-1.5 sm:w-56">
            <Label htmlFor="avito-account" className="block text-xs text-muted-foreground">
              Аккаунт
            </Label>
            <select
              id="avito-account"
              className={selectClass}
              value={accountId ?? ""}
              onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : undefined)}
            >
              <option value="">Все аккаунты</option>
              {st.accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>
        ) : null}
      </div>

      {q.isLoading && !d ? (
        <PageLoading rows={3} />
      ) : q.isError ? (
        <ErrorState message="Не удалось загрузить данные Avito." onRetry={() => void q.refetch()} />
      ) : d ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <Stat title="Новых обращений" value={String(d.summary.new)} />
            <Stat
              title="Первый ответ (медиана)"
              value={formatDuration(d.summary.reply_median_seconds, work)}
              hint={`норма ${formatDuration(d.norm_seconds, work)}`}
            />
            <Stat title="Дольше нормы" value={formatPercent(d.summary.late_share)} hint={`${d.summary.late} из ${d.summary.new}`} />
            <Stat
              title="Без ответа сейчас"
              value={String(d.summary.unanswered_now)}
              hint={`дольше нормы: ${d.summary.unanswered_late}`}
              alert={d.summary.unanswered_late > 0}
            />
            <Stat
              title="Связано со сделками"
              value={formatPercent(d.summary.linked_share)}
              hint={`${d.summary.linked} · выиграно ${d.summary.won}`}
            />
          </div>

          {!d.summary.new && !d.unanswered.length ? (
            <EmptyState title="Обращений за период нет" description={st?.configured ? undefined : "Подключите аккаунты Avito."} />
          ) : null}

          {d.unanswered.length ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Ждут ответа</CardTitle>
                <CardDescription>{d.definitions.unanswered}</CardDescription>
              </CardHeader>
              <CardContent>
                <ChatTable rows={d.unanswered} mode="waiting" onOpen={setOpenChat} />
              </CardContent>
            </Card>
          ) : null}

          {d.slowest.length ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Обращения за период</CardTitle>
                <CardDescription>{d.definitions.reply} Сначала самые медленные.</CardDescription>
              </CardHeader>
              <CardContent>
                <ChatTable rows={d.slowest} mode="reply" onOpen={setOpenChat} />
              </CardContent>
            </Card>
          ) : null}

          <div className="grid gap-6 xl:grid-cols-2">
            {d.by_item.length ? (
              <Card className="min-w-0">
                <CardHeader>
                  <CardTitle className="text-base">Объявления</CardTitle>
                  <CardDescription>С каких объявлений пришли обращения и чем закончились.</CardDescription>
                </CardHeader>
                <CardContent>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Объявление</TableHead>
                        <TableHead>Обращений</TableHead>
                        <TableHead>Ответ (медиана)</TableHead>
                        <TableHead>Сделок / выиграно</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {d.by_item.map((i) => (
                        <TableRow key={`${i.item_id}-${i.title}`}>
                          <TableCell>
                            {i.url ? (
                              <a href={i.url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                                {i.title}
                              </a>
                            ) : (
                              i.title
                            )}
                            <p className="text-xs text-muted-foreground">{i.account}</p>
                          </TableCell>
                          <TableCell>{i.new}</TableCell>
                          <TableCell className="whitespace-nowrap">{formatDuration(i.reply_median_seconds, work)}</TableCell>
                          <TableCell>
                            {i.linked} / {i.won}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            ) : null}
            {d.by_account.length > 1 ? (
              <Card className="min-w-0">
                <CardHeader>
                  <CardTitle className="text-base">По аккаунтам</CardTitle>
                </CardHeader>
                <CardContent>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Аккаунт</TableHead>
                        <TableHead>Обращений</TableHead>
                        <TableHead>Ответ (медиана)</TableHead>
                        <TableHead>Дольше нормы</TableHead>
                        <TableHead>Без ответа</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {d.by_account.map((a) => (
                        <TableRow key={a.account_id}>
                          <TableCell>{a.name}</TableCell>
                          <TableCell>{a.new}</TableCell>
                          <TableCell className="whitespace-nowrap">{formatDuration(a.reply_median_seconds, work)}</TableCell>
                          <TableCell>{formatPercent(a.late_share)}</TableCell>
                          <TableCell>{a.unanswered_now}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            ) : null}
          </div>
        </>
      ) : null}

      {openChat ? <Conversation chatId={openChat} onClose={() => setOpenChat(null)} /> : null}
    </div>
  );
}

function ChatTable({ rows, mode, onOpen }: { rows: AvitoChatRow[]; mode: "waiting" | "reply"; onOpen: (id: string) => void }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Клиент</TableHead>
          <TableHead>Объявление</TableHead>
          <TableHead>{mode === "waiting" ? "Ждёт" : "Первый ответ"}</TableHead>
          <TableHead>Сделка</TableHead>
          <TableHead />
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => {
          const value = mode === "waiting" || r.reply_seconds === null ? r.waiting_seconds : r.reply_seconds;
          return (
            <TableRow key={r.chat_id}>
              <TableCell>
                {r.client_name ?? "Клиент"}
                <p className="text-xs text-muted-foreground">
                  {r.account} · {formatDateTime(r.first_in_at)}
                </p>
              </TableCell>
              <TableCell className="max-w-xs truncate">{r.item_title ?? "—"}</TableCell>
              <TableCell className="whitespace-nowrap">
                <span className={cn(r.late && "font-semibold text-red-700")}>{formatDuration(value, work)}</span>
                {mode === "reply" && r.reply_seconds === null ? (
                  <Badge variant="destructive" className="ml-2">
                    нет ответа
                  </Badge>
                ) : null}
              </TableCell>
              <TableCell>
                {r.deal ? (
                  <>
                    <Link href={`/deals/${r.deal.deal_id}`} className="text-primary hover:underline">
                      №{r.deal.bitrix_id}
                    </Link>{" "}
                    {r.deal.won ? <Badge variant="success">выиграна</Badge> : r.deal.lost ? <Badge variant="secondary">проиграна</Badge> : null}
                    <div>
                      <BitrixLink href={r.deal.bitrix_url} />
                    </div>
                  </>
                ) : (
                  <span className="text-xs text-muted-foreground">не связана</span>
                )}
              </TableCell>
              <TableCell className="text-right">
                <div className="flex items-center justify-end gap-2 whitespace-nowrap">
                  <Button size="sm" variant="ghost" onClick={() => onOpen(r.chat_id)}>
                    Переписка
                  </Button>
                  <a href={r.chat_url} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline">
                    в Авито ↗
                  </a>
                </div>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

function Conversation({ chatId, onClose }: { chatId: string; onClose: () => void }) {
  const q = useAvitoChat(chatId);
  const c = q.data;
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="Переписка">
      <button type="button" aria-label="Закрыть" className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-lg flex-col bg-background shadow-xl">
        <div className="flex items-start justify-between gap-2 border-b border-border p-4">
          <div>
            <p className="font-medium">{c?.client_name ?? "Переписка"}</p>
            <p className="text-xs text-muted-foreground">
              {[c?.account, c?.item_title].filter(Boolean).join(" · ")}
            </p>
            {c ? (
              <a href={c.chat_url} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline">
                Открыть в Авито ↗
              </a>
            ) : null}
          </div>
          <Button size="sm" variant="ghost" onClick={onClose}>
            Закрыть
          </Button>
        </div>
        <div className="flex-1 space-y-2 overflow-y-auto p-4">
          {q.isLoading ? <PageLoading rows={1} /> : null}
          {c?.messages.map((m) => (
            <div
              key={m.id}
              className={cn(
                "max-w-[85%] rounded-lg px-3 py-2 text-sm",
                m.is_system ? "mx-auto bg-muted text-xs text-muted-foreground" : m.direction === "out" ? "ml-auto bg-primary/10" : "bg-muted",
              )}
            >
              <p className="whitespace-pre-wrap break-words">{m.text || "—"}</p>
              <p className="mt-1 text-[10px] text-muted-foreground">
                {m.is_system ? "автоответ / система · " : m.direction === "out" ? "мы · " : "клиент · "}
                {formatDateTime(m.created)}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Stat({ title, value, hint, alert }: { title: string; value: string; hint?: string; alert?: boolean }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className={cn("font-serif text-2xl font-semibold", alert && "text-red-700")}>{value}</p>
        {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}

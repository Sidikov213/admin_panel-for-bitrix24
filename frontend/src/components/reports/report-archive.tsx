"use client";

import Link from "next/link";
import { useState } from "react";
import { BitrixLink } from "@/components/common/scope-filters";
import { PageLoading } from "@/components/common/page-states";
import { useAuth } from "@/components/providers/auth-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useReportArchive, useReportDetail, useReportMutations } from "@/hooks/queries";
import { formatDateTime, formatDuration, formatMoney, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ReportDetail, ReportKind, ReportSendResult } from "@/types/api";

const KINDS: { value: ReportKind | undefined; label: string }[] = [
  { value: undefined, label: "Все" },
  { value: "daily", label: "Дневные" },
  { value: "weekly", label: "Недельные" },
  { value: "monthly", label: "Месячные" },
];
const WEEKDAY: Record<string, string> = { mon: "понедельник", tue: "вторник", wed: "среда", thu: "четверг", fri: "пятница", sat: "суббота", sun: "воскресенье" };
const SKIP: Record<string, string> = {
  telegram_not_configured: "Telegram не настроен — отчёт сохранён только в панели",
  no_recipients: "не заданы получатели (TELEGRAM_REPORT_CHAT_IDS)",
};

function sendText(r: ReportSendResult): string {
  if (r.status === "sent") return `Отправлено: ${r.sent_to}${r.errors?.length ? ` · ошибок: ${r.errors.length}` : ""}`;
  if (r.status === "failed") return `Не отправлено: ${r.errors?.join("; ")}`;
  return SKIP[r.reason ?? ""] ?? `Пропущено: ${r.reason}`;
}

export function ReportArchive() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [kind, setKind] = useState<ReportKind | undefined>();
  const [openId, setOpenId] = useState<number | null>(null);
  const archive = useReportArchive(kind);
  const { generate, send } = useReportMutations();
  const s = archive.data?.schedule;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Ежедневные и недельные отчёты</CardTitle>
        <CardDescription>
          {s
            ? s.enabled
              ? `Дневной — в ${s.daily_time} по рабочим дням, недельный — ${WEEKDAY[s.weekly_day] ?? s.weekly_day} в ${s.weekly_time} за прошлую неделю. ` +
                (s.telegram_configured && s.recipients
                  ? `Получателей в Telegram: ${s.recipients}.`
                  : "Telegram не настроен — отчёты сохраняются только здесь.")
              : "Автоматические отчёты выключены (REPORTS_ENABLED=false)."
            : null}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          {KINDS.map((k) => (
            <Button key={k.label} size="sm" variant={kind === k.value ? "default" : "outline"} onClick={() => setKind(k.value)}>
              {k.label}
            </Button>
          ))}
          {isAdmin ? (
            <span className="flex flex-wrap gap-2 sm:ml-auto">
              {(["daily", "weekly", "monthly"] as ReportKind[]).map((k) => (
                <Button
                  key={k}
                  size="sm"
                  variant="outline"
                  disabled={generate.isPending}
                  onClick={() => generate.mutate({ kind: k }, { onSuccess: (r) => setOpenId(r.id) })}
                >
                  {k === "daily" ? "Сформировать за сегодня" : k === "weekly" ? "За эту неделю" : "За этот месяц"}
                </Button>
              ))}
            </span>
          ) : null}
        </div>
        {send.data ? <p className="text-sm">{sendText(send.data)}</p> : null}

        {archive.isLoading ? (
          <PageLoading rows={1} />
        ) : !archive.data?.items.length ? (
          <p className="text-sm text-muted-foreground">Отчётов пока нет. Первый появится в {s?.daily_time ?? "20:00"} рабочего дня.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Отчёт</TableHead>
                <TableHead>Новых / выиграно / проиграно</TableHead>
                <TableHead>Просрочек</TableHead>
                <TableHead>Telegram</TableHead>
                {isAdmin ? <TableHead /> : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {archive.data.items.map((r) => (
                <TableRow key={r.id} className={cn(openId === r.id && "bg-muted/50")}>
                  <TableCell>
                    <button type="button" className="text-left font-medium text-primary hover:underline" onClick={() => setOpenId(openId === r.id ? null : r.id)}>
                      {r.title}
                    </button>
                  </TableCell>
                  <TableCell>
                    {r.headline.new ?? 0} / {r.headline.won ?? 0} / {r.headline.lost ?? 0}
                  </TableCell>
                  <TableCell>{r.headline.overdue ?? 0}</TableCell>
                  <TableCell className="whitespace-nowrap">
                    {r.sent_at ? (
                      <Badge variant={r.send_error ? "warning" : "success"} title={r.send_error ?? undefined}>
                        отправлен {formatDateTime(r.sent_at)}
                      </Badge>
                    ) : (
                      <Badge variant="secondary">не отправлен</Badge>
                    )}
                  </TableCell>
                  {isAdmin ? (
                    <TableCell className="text-right">
                      <Button size="sm" variant="ghost" disabled={send.isPending} onClick={() => send.mutate(r.id)}>
                        Отправить
                      </Button>
                    </TableCell>
                  ) : null}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}

        {openId !== null ? <ReportView id={openId} /> : null}
      </CardContent>
    </Card>
  );
}

function Delta({ now, was, money, higherIsBetter = true }: { now: number; was: number; money?: boolean; higherIsBetter?: boolean }) {
  if (now === was) return <span className="text-xs text-muted-foreground"> · как было</span>;
  const good = now > was === higherIsBetter;
  return (
    <span className={cn("text-xs", good ? "text-emerald-700" : "text-red-700")}>
      {" "}
      · было {money ? formatMoney(was) : was}
    </span>
  );
}

function ReportView({ id }: { id: number }) {
  const q = useReportDetail(id);
  if (q.isLoading) return <PageLoading rows={2} />;
  if (!q.data) return null;
  const { data } = q.data as ReportDetail;
  const m = data.metrics;
  const p = data.previous;
  const work = { work: true };
  const tiles: [string, React.ReactNode][] = [
    ["Новых сделок", <>{m.new}<Delta now={m.new} was={p.new} /></>],
    ["Успешно закрыто", <>{m.won}{m.won ? ` · ${formatMoney(m.won_sum)}` : ""}<Delta now={m.won} was={p.won} /></>],
    ["Проиграно", <>{m.lost}<Delta now={m.lost} was={p.lost} higherIsBetter={false} /></>],
    ["Просрочек за период", <>{m.overdue}<Delta now={m.overdue} was={p.overdue} higherIsBetter={false} /></>],
    ["Незакрытых просрочек", m.overdue_open_now],
    ["Зависших сделок", `${m.stuck_now} из ${m.open_now}`],
    ["Реакция до контакта", formatDuration(m.reaction_median_seconds, work)],
    ["Без следующего дела", m.no_next_activity_now],
  ];

  return (
    <div className="space-y-5 rounded-xl border border-border p-4">
      <h3 className="font-serif text-xl font-semibold">{data.title}</h3>
      {data.data_warning ? <p className="text-sm text-amber-800">{data.data_warning}</p> : null}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {tiles.map(([label, value]) => (
          <div key={label} className="rounded-lg bg-muted/50 p-3">
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="font-serif text-lg font-semibold">{value}</p>
          </div>
        ))}
      </div>
      {data.plan ? (
        <p className="text-sm">
          План: {formatMoney(data.plan.fact)} из {formatMoney(data.plan.plan)} — {formatPercent(data.plan.percent)}
        </p>
      ) : null}

      {data.ai_summary?.status === "ok" ? (
        <div className="rounded-lg bg-muted/50 p-4 text-sm">
          <h4 className="mb-1 font-medium">Вывод ИИ</h4>
          <p>{data.ai_summary.headline}</p>
          {data.ai_summary.points.length ? (
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {data.ai_summary.points.map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ul>
          ) : null}
          {data.ai_summary.recommendations.length ? (
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-muted-foreground">
              {data.ai_summary.recommendations.map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ol>
          ) : null}
          <Link href="/ai" className="mt-2 inline-block text-primary hover:underline">
            Полный анализ →
          </Link>
        </div>
      ) : data.ai_summary?.status === "error" ? (
        <p className="text-sm text-muted-foreground">Вывод ИИ для этого отчёта получить не удалось.</p>
      ) : null}

      {data.managers.length ? (
        <div className="min-w-0">
          <h4 className="mb-2 font-medium">По менеджерам</h4>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Менеджер</TableHead>
                <TableHead>Новых</TableHead>
                <TableHead>Выиграно</TableHead>
                <TableHead>Проиграно</TableHead>
                <TableHead>Просрочек</TableHead>
                <TableHead>Висит / доля</TableHead>
                <TableHead>Зависло / доля</TableHead>
                <TableHead>Реакция</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.managers.map((r) => (
                <TableRow key={r.manager_id}>
                  <TableCell>
                    <Link href={`/managers/${r.manager_id}`} className="text-primary hover:underline">
                      {r.name}
                    </Link>
                  </TableCell>
                  <TableCell>{r.new}</TableCell>
                  <TableCell>{r.won}</TableCell>
                  <TableCell>{r.lost}</TableCell>
                  <TableCell>{r.overdue}</TableCell>
                  <TableCell className="whitespace-nowrap">
                    {r.overdue_open} · {formatPercent(r.overdue_share)}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    {r.stuck} · {formatPercent(r.stuck_share)}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">{formatDuration(r.reaction_median_seconds, work)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-2">
        {data.problem_deals.length ? (
          <div className="min-w-0">
            <h4 className="mb-2 font-medium">Требуют внимания</h4>
            <ul className="space-y-2 text-sm">
              {data.problem_deals.map((d) => (
                <li key={d.deal_id}>
                  <Link href={`/deals/${d.deal_id}`} className="text-primary hover:underline">
                    №{d.bitrix_id} {d.title}
                  </Link>{" "}
                  <span className="text-muted-foreground">
                    — {d.stage} {formatDuration(d.in_stage_seconds, { work: d.unit !== "calendar_days" })} (срок {d.rule})
                    {d.manager ? ` · ${d.manager}` : ""}
                  </span>{" "}
                  <BitrixLink href={d.bitrix_url} />
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {data.card_quality.no_next_activity ? (
          <div className="min-w-0">
            <h4 className="mb-2 font-medium">Качество карточек: без следующего дела — {data.card_quality.no_next_activity}</h4>
            {data.card_quality.checked ? (
              <p className="mb-2 text-sm text-muted-foreground">
                С нарушениями регламента: {data.card_quality.with_issues} из {data.card_quality.checked} (
                {formatPercent(data.card_quality.share ?? null)}).{" "}
                <Link href="/quality" className="text-primary hover:underline">
                  Подробнее →
                </Link>
              </p>
            ) : null}
            {data.card_quality.by_check?.length ? (
              <ul className="mb-2 space-y-1 text-sm">
                {data.card_quality.by_check.map((b) => (
                  <li key={b.code}>
                    {b.label}: {b.count}
                  </li>
                ))}
              </ul>
            ) : null}
            <ul className="space-y-2 text-sm">
              {data.card_quality.deals.map((d) => (
                <li key={d.deal_id}>
                  <Link href={`/deals/${d.deal_id}`} className="text-primary hover:underline">
                    №{d.bitrix_id} {d.title}
                  </Link>
                  {d.opportunity ? <span className="text-muted-foreground"> — {formatMoney(d.opportunity)}</span> : null}{" "}
                  <BitrixLink href={d.bitrix_url} />
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      {data.problem_stages.length ? (
        <div>
          <h4 className="mb-2 font-medium">Проблемные этапы</h4>
          <ul className="space-y-1 text-sm">
            {data.problem_stages.map((s) => (
              <li key={`${s.pipeline}-${s.name}`}>
                {s.name} <span className="text-muted-foreground">({s.pipeline})</span> — зависло {s.stuck} из {s.open} · просрочек {s.overdue}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <details>
        <summary className="cursor-pointer text-sm text-muted-foreground">Текст, как он ушёл в Telegram</summary>
        <pre className="mt-2 whitespace-pre-wrap break-words font-sans text-sm">{q.data.text}</pre>
      </details>
    </div>
  );
}

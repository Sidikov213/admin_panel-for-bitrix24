"use client";

import { useState } from "react";
import { isoDate } from "@/components/common/period-picker";
import { EmptyState, PageLoading } from "@/components/common/page-states";
import { useAuth } from "@/components/providers/auth-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAiAnalyses, useAiAnalysis, useAiStatus, useRunAiAnalysis } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { formatDate, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AiAnalysis, ReportKind } from "@/types/api";

const KIND_LABEL: Record<ReportKind, string> = { daily: "День", weekly: "Неделя", monthly: "Месяц" };

function periodText(a: { kind: ReportKind; period_start: string; period_end: string }) {
  return a.period_start === a.period_end ? formatDate(a.period_start) : `${formatDate(a.period_start)} – ${formatDate(a.period_end)}`;
}

function errorText(e: unknown): string {
  if (e instanceof ApiError && typeof e.detail === "string") return e.detail;
  return "Не удалось получить вывод ИИ. Попробуйте позже.";
}

export function AiView() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const status = useAiStatus();
  const list = useAiAnalyses();
  const run = useRunAiAnalysis();
  const [kind, setKind] = useState<ReportKind>("weekly");
  const [day, setDay] = useState(() => isoDate(new Date()));
  const [force, setForce] = useState(false);
  const [picked, setPicked] = useState<number | null>(null);
  const st = status.data;
  const latestOk = list.data?.items.find((i) => i.status === "ok")?.id ?? null;
  const openId = picked ?? latestOk;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-serif text-3xl font-semibold">ИИ-анализ</h1>
        <p className="text-sm text-muted-foreground">
          Выводы по отделу и менеджерам, повторяющиеся проблемы и рекомендации. ИИ не считает показатели сам: он получает уже
          посчитанные панелью цифры (те же, что в отчётах) и объясняет их. Тот же вывод добавляется в ежедневный и недельный
          отчёт.
        </p>
      </div>

      {st ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{st.configured ? "ИИ подключён" : "ИИ не подключён"}</CardTitle>
            <CardDescription>
              {st.configured
                ? st.send_texts
                  ? "В модель уходят цифры, а также тексты комментариев и переписки Avito без телефонов, e-mail и ссылок."
                  : "В модель уходят только цифры: менеджеры под псевдонимами «Менеджер-<id>», без клиентов, названий сделок, комментариев и ссылок. Имена подставляются обратно только здесь, в панели."
                : "Ключ Claude API задаётся на сервере в .env (ANTHROPIC_API_KEY), в панели он не хранится. Пока ключа нет, никакие данные наружу не отправляются."}
            </CardDescription>
          </CardHeader>
          {st.configured ? (
            <CardContent className="flex flex-wrap gap-2 text-sm">
              <Badge variant="secondary">
                модель {st.model} · {st.effort}
              </Badge>
              <Badge variant={st.send_texts ? "warning" : "success"}>{st.send_texts ? "цифры и тексты" : "только цифры"}</Badge>
              <Badge variant="secondary">{st.in_reports ? "в отчётах: да" : "в отчётах: нет"}</Badge>
              <Badge variant="secondary">{st.script_configured ? "скрипт продаж задан" : "скрипт продаж не задан"}</Badge>
              <Badge variant={st.used_today >= st.daily_limit ? "warning" : "secondary"}>
                запросов сегодня {st.used_today} из {st.daily_limit}
              </Badge>
            </CardContent>
          ) : null}
        </Card>
      ) : null}

      {isAdmin && st?.configured ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Новый анализ</CardTitle>
            <CardDescription>Период — день, неделя (пн–вс) или месяц, в который входит выбранная дата.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex gap-2">
                {(["daily", "weekly", "monthly"] as ReportKind[]).map((k) => (
                  <Button key={k} size="sm" variant={kind === k ? "default" : "outline"} onClick={() => setKind(k)}>
                    {KIND_LABEL[k]}
                  </Button>
                ))}
              </div>
              <div className="space-y-1">
                <Label htmlFor="ai-day" className="text-xs">
                  Дата
                </Label>
                <Input id="ai-day" type="date" value={day} max={isoDate(new Date())} onChange={(e) => setDay(e.target.value)} className="h-9 w-40" />
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
                спросить заново, даже если цифры не изменились
              </label>
              <Button
                disabled={run.isPending || !day}
                onClick={() => run.mutate({ kind, day, force }, { onSuccess: (r) => setPicked(r.id) })}
              >
                {run.isPending ? "Анализирую…" : "Запустить анализ"}
              </Button>
            </div>
            {run.isPending ? <p className="text-sm text-muted-foreground">Обычно это занимает до минуты.</p> : null}
            {run.isError ? <p className="text-sm text-red-700">{errorText(run.error)}</p> : null}
          </CardContent>
        </Card>
      ) : null}

      {openId !== null ? <AnalysisView id={openId} /> : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">История</CardTitle>
        </CardHeader>
        <CardContent>
          {list.isLoading ? (
            <PageLoading rows={1} />
          ) : !list.data?.items.length ? (
            <EmptyState
              title="Анализов пока нет"
              description={st?.configured ? "Запустите первый анализ или дождитесь отчёта." : "Появятся после подключения ИИ."}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Период</TableHead>
                  <TableHead>Главный вывод</TableHead>
                  <TableHead>Источник</TableHead>
                  <TableHead>Когда</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.data.items.map((a) => (
                  <TableRow key={a.id} className={cn(openId === a.id && "bg-muted/50")}>
                    <TableCell className="whitespace-nowrap">
                      <button
                        type="button"
                        className="text-left font-medium text-primary hover:underline disabled:text-muted-foreground disabled:no-underline"
                        disabled={a.status !== "ok"}
                        onClick={() => setPicked(a.id)}
                      >
                        {KIND_LABEL[a.kind]} · {periodText(a)}
                      </button>
                    </TableCell>
                    <TableCell className="min-w-[16rem]">
                      {a.status === "ok" ? a.headline : <span className="text-red-700">Ошибка: {a.error}</span>}
                    </TableCell>
                    <TableCell>{a.trigger === "report" ? "отчёт" : "вручную"}</TableCell>
                    <TableCell className="whitespace-nowrap">{formatDateTime(a.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Points({ title, items, tone }: { title: string; items: string[]; tone?: "risk" }) {
  if (!items.length) return null;
  return (
    <div className="min-w-0">
      <h4 className="mb-2 font-medium">{title}</h4>
      <ul className={cn("list-disc space-y-1 pl-5 text-sm", tone === "risk" && "marker:text-red-600")}>
        {items.map((t, i) => (
          <li key={i}>{t}</li>
        ))}
      </ul>
    </div>
  );
}

function AnalysisView({ id }: { id: number }) {
  const q = useAiAnalysis(id);
  if (q.isLoading) return <PageLoading rows={2} />;
  const a = q.data as AiAnalysis | undefined;
  if (!a?.result) return null;
  const r = a.result;
  const c = r.communication;

  return (
    <Card>
      <CardHeader>
        <CardDescription>
          {KIND_LABEL[a.kind]} · {periodText(a)}
        </CardDescription>
        <CardTitle className="font-serif text-xl leading-snug">{r.headline}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid gap-5 lg:grid-cols-2">
          <Points title="По отделу" items={r.department} />
          <Points title="Риски" items={r.risks} tone="risk" />
        </div>

        {r.recommendations.length ? (
          <div className="rounded-lg bg-muted/50 p-4">
            <h4 className="mb-2 font-medium">Что сделать</h4>
            <ol className="list-decimal space-y-1 pl-5 text-sm">
              {r.recommendations.map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ol>
          </div>
        ) : null}

        {r.managers.length ? (
          <div>
            <h4 className="mb-2 font-medium">По менеджерам</h4>
            <div className="grid gap-3 md:grid-cols-2">
              {r.managers.map((m) => (
                <div key={m.manager} className="min-w-0 space-y-2 rounded-lg border border-border p-3 text-sm">
                  <p className="font-medium">{m.manager}</p>
                  <p>{m.summary}</p>
                  {m.strengths.length ? <p className="text-emerald-700">+ {m.strengths.join(" · ")}</p> : null}
                  {m.problems.length ? <p className="text-red-700">− {m.problems.join(" · ")}</p> : null}
                  {m.actions.length ? (
                    <ul className="list-disc pl-5 text-muted-foreground">
                      {m.actions.map((t, i) => (
                        <li key={i}>{t}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {r.repeated_problems.length ? (
          <div>
            <h4 className="mb-2 font-medium">Повторяющиеся проблемы</h4>
            <ul className="space-y-2 text-sm">
              {r.repeated_problems.map((p, i) => (
                <li key={i}>
                  <span className="font-medium">{p.problem}</span>
                  {p.who.length ? <span className="text-muted-foreground"> — {p.who.join(", ")}</span> : null}
                  <p className="text-muted-foreground">{p.evidence}</p>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {c.assessed ? (
          <div className="grid gap-5 lg:grid-cols-2">
            <Points title="Комментарии в карточках" items={c.comments} />
            <Points title="Ответы в Avito" items={c.avito_replies} />
            <Points title="Соответствие скрипту" items={c.script} />
            <Points title="Примеры" items={c.examples} />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Качество комментариев и ответов клиентам не оценивалось: тексты в ИИ не отправлялись. Это включается на сервере
            (AI_SEND_TEXTS=true) после согласия компании на передачу переписки во внешний сервис.
          </p>
        )}

        <p className="text-xs text-muted-foreground">
          {a.model} · {formatDateTime(a.created_at)} · токенов {a.input_tokens} → {a.output_tokens}
          {a.texts_sent ? " · с текстами" : " · только цифры"}
        </p>
        {a.context ? (
          <details>
            <summary className="cursor-pointer text-sm text-muted-foreground">Что было отправлено в ИИ</summary>
            <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted/50 p-3 text-xs">
              {JSON.stringify(a.context, null, 2)}
            </pre>
          </details>
        ) : null}
      </CardContent>
    </Card>
  );
}

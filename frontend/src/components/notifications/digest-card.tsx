"use client";

import { useState } from "react";
import { useAuth } from "@/components/providers/auth-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useDigestPreview, useNotificationStatus, useSendDigest } from "@/hooks/queries";
import { formatDateTime } from "@/lib/format";
import type { DigestSendResult } from "@/types/api";

const DAYS_LABEL: Record<string, string> = {
  "mon-fri": "по будням",
  "mon-sun": "каждый день",
  "*": "каждый день",
};

const SKIP_REASON: Record<string, string> = {
  telegram_not_configured: "не задан TELEGRAM_BOT_TOKEN",
  no_recipients: "нет получателей: задайте TELEGRAM_CHAT_ID или chat id менеджеров",
  already_sent_today: "сегодня уже отправлен",
};

function sendResultText(r: DigestSendResult): string {
  if (r.status === "sent") {
    const parts = [r.team_sent ? "общий чат" : null, r.managers_sent ? `менеджерам: ${r.managers_sent}` : null];
    const errors = r.errors?.length ? ` · ошибок: ${r.errors.length}` : "";
    return `Отправлено (${parts.filter(Boolean).join(", ")})${errors}`;
  }
  if (r.status === "failed") return `Не отправлено: ${r.errors?.join("; ") ?? "ошибка Telegram"}`;
  return `Пропущено: ${SKIP_REASON[r.reason ?? ""] ?? r.reason ?? ""}`;
}

export function DigestCard() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const status = useNotificationStatus();
  const [showPreview, setShowPreview] = useState(false);
  const preview = useDigestPreview(isAdmin && showPreview);
  const send = useSendDigest();

  const s = status.data;
  if (!s) return null;
  const last = s.last_sent;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Ежедневный дайджест в Telegram</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          <p>
            Бот:{" "}
            <Badge variant={s.telegram_configured ? "success" : "secondary"}>
              {s.telegram_configured ? "настроен" : "не настроен"}
            </Badge>
          </p>
          <p>
            Общий чат:{" "}
            <Badge variant={s.team_chat_configured ? "success" : "secondary"}>
              {s.team_chat_configured ? "задан" : "не задан"}
            </Badge>
          </p>
          <p>Менеджеров с Telegram: {s.managers_with_chat}</p>
        </div>
        <p className="text-muted-foreground">
          {!s.telegram_configured
            ? "Автоотправка выключена: задайте TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в .env."
            : !s.enabled
              ? "Автоотправка выключена (DIGEST_ENABLED=false). Отправить вручную можно кнопкой ниже."
              : `Отправка ${DAYS_LABEL[s.days] ?? s.days} в ${s.time} (${s.timezone}). «Без движения» — ${s.stale_days}+ дн.`}
        </p>
        <p className="text-muted-foreground">
          Последняя отправка:{" "}
          {last?.at
            ? `${formatDateTime(last.at)}${last.managers_sent ? ` · менеджерам: ${last.managers_sent}` : ""}${
                last.errors ? ` · ошибок: ${last.errors}` : ""
              }`
            : "ещё не было"}
        </p>

        {isAdmin ? (
          <div className="space-y-3 pt-1">
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={() => setShowPreview((v) => !v)}>
                {showPreview ? "Скрыть предпросмотр" : "Предпросмотр"}
              </Button>
              <Button
                size="sm"
                disabled={!s.telegram_configured || send.isPending}
                onClick={() => send.mutate()}
              >
                {send.isPending ? "Отправка…" : "Отправить сейчас"}
              </Button>
            </div>
            {send.data ? <p>{sendResultText(send.data)}</p> : null}
            {send.isError ? <p className="text-destructive">Не удалось отправить дайджест.</p> : null}

            {showPreview ? (
              preview.isLoading ? (
                <p className="text-muted-foreground">Собираем дайджест…</p>
              ) : preview.isError ? (
                <p className="text-destructive">Не удалось собрать предпросмотр.</p>
              ) : preview.data ? (
                <div className="space-y-3">
                  <PreviewBlock title="Общий чат" text={preview.data.team} />
                  {preview.data.managers.map((m) => (
                    <PreviewBlock
                      key={m.manager_id}
                      title={`${m.name}${m.has_chat ? "" : " — chat id не задан, не будет отправлено"}`}
                      text={m.text}
                    />
                  ))}
                </div>
              ) : null
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function PreviewBlock({ title, text }: { title: string; text: string }) {
  return (
    <details className="rounded-lg border border-border" open={title === "Общий чат"}>
      <summary className="cursor-pointer px-3 py-2 font-medium">{title}</summary>
      <pre className="whitespace-pre-wrap break-words border-t border-border px-3 py-2 font-sans text-sm">{text}</pre>
    </details>
  );
}

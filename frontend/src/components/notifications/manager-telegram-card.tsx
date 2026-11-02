"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useUpdateManagerChat } from "@/hooks/queries";
import { ApiError } from "@/lib/api";

const CHAT_ID_RE = /^(-?\d{1,20}|@[A-Za-z0-9_]{5,32})$/;

export function ManagerTelegramCard({ managerId, chatId }: { managerId: number; chatId: string | null | undefined }) {
  const [value, setValue] = useState(chatId ?? "");
  const update = useUpdateManagerChat(managerId);
  const trimmed = value.trim();
  const invalid = trimmed !== "" && !CHAT_ID_RE.test(trimmed);
  const unchanged = trimmed === (chatId ?? "");

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Личный дайджест в Telegram</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">
          Каждое утро менеджер получит список своих просроченных дел и сделок без движения. Менеджер должен написать
          боту /start, затем укажите здесь его chat id.
        </p>
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!invalid) update.mutate(trimmed || null);
          }}
        >
          <div className="space-y-1">
            <Label htmlFor="tg-chat">Chat id</Label>
            <Input
              id="tg-chat"
              className="w-56"
              placeholder="например 123456789"
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          </div>
          <Button type="submit" size="sm" disabled={invalid || unchanged || update.isPending}>
            {update.isPending ? "Сохранение…" : "Сохранить"}
          </Button>
        </form>
        {invalid ? <p className="text-destructive">Число (для групп — со знаком минус) или @username.</p> : null}
        {update.isSuccess && unchanged ? <p className="text-muted-foreground">Сохранено.</p> : null}
        {update.isError ? (
          <p className="text-destructive">
            {update.error instanceof ApiError && update.error.status === 403
              ? "Недостаточно прав."
              : "Не удалось сохранить."}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

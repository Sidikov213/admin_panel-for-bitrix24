"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useManagers, useTargetMutations } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { managerName } from "@/lib/format";
import type { PeriodType } from "@/types/api";

type Preset = { key: string; label: string; type: PeriodType; range: (today: Date) => [Date, Date] };

const PRESETS: Preset[] = [
  {
    key: "this_month",
    label: "Этот месяц",
    type: "month",
    range: (d) => [new Date(d.getFullYear(), d.getMonth(), 1), new Date(d.getFullYear(), d.getMonth() + 1, 0)],
  },
  {
    key: "next_month",
    label: "Следующий месяц",
    type: "month",
    range: (d) => [new Date(d.getFullYear(), d.getMonth() + 1, 1), new Date(d.getFullYear(), d.getMonth() + 2, 0)],
  },
  {
    key: "this_quarter",
    label: "Этот квартал",
    type: "quarter",
    range: (d) => {
      const q = Math.floor(d.getMonth() / 3) * 3;
      return [new Date(d.getFullYear(), q, 1), new Date(d.getFullYear(), q + 3, 0)];
    },
  },
  {
    key: "this_week",
    label: "Эта неделя",
    type: "week",
    range: (d) => {
      const monday = new Date(d.getFullYear(), d.getMonth(), d.getDate() - ((d.getDay() + 6) % 7));
      return [monday, new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + 6)];
    },
  },
  {
    key: "this_year",
    label: "Этот год",
    type: "year",
    range: (d) => [new Date(d.getFullYear(), 0, 1), new Date(d.getFullYear(), 11, 31)],
  },
];

function isoDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (typeof error.detail === "string") return error.detail;
    if (Array.isArray(error.detail)) return "Проверьте поля формы.";
    if (error.status === 403) return "Недостаточно прав.";
  }
  return "Не удалось сохранить цель.";
}

const selectClass =
  "flex h-10 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function TargetForm() {
  const managers = useManagers();
  const { create } = useTargetMutations();
  const [presetKey, setPresetKey] = useState("this_month");
  const initial = PRESETS[0].range(new Date());
  const [start, setStart] = useState(isoDate(initial[0]));
  const [end, setEnd] = useState(isoDate(initial[1]));
  const [periodType, setPeriodType] = useState<PeriodType>("month");
  const [managerId, setManagerId] = useState("");
  const [amount, setAmount] = useState("");

  const activeManagers = useMemo(
    () => (managers.data ?? []).filter((m) => m.is_active !== false).sort((a, b) => managerName(a).localeCompare(managerName(b))),
    [managers.data],
  );

  const applyPreset = (key: string) => {
    setPresetKey(key);
    const preset = PRESETS.find((p) => p.key === key);
    if (!preset) return;
    const [s, e] = preset.range(new Date());
    setStart(isoDate(s));
    setEnd(isoDate(e));
    setPeriodType(preset.type);
  };

  const amountValue = amount.replace(/\s/g, "").replace(",", ".");
  const amountValid = /^\d+(\.\d{1,2})?$/.test(amountValue) && Number(amountValue) > 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Новая цель</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6 lg:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            if (!amountValid) return;
            create.mutate(
              {
                manager_id: managerId ? Number(managerId) : null,
                period_type: periodType,
                period_start: start,
                period_end: end,
                amount: amountValue,
              },
              { onSuccess: () => setAmount("") },
            );
          }}
        >
          <div className="space-y-1 lg:col-span-2">
            <Label htmlFor="target-manager">Для кого</Label>
            <select id="target-manager" className={selectClass} value={managerId} onChange={(e) => setManagerId(e.target.value)}>
              <option value="">Весь отдел</option>
              {activeManagers.map((m) => (
                <option key={m.id} value={m.id}>
                  {managerName(m)}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="target-preset">Период</Label>
            <select id="target-preset" className={selectClass} value={presetKey} onChange={(e) => applyPreset(e.target.value)}>
              {PRESETS.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}
                </option>
              ))}
              <option value="custom">Свои даты</option>
            </select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="target-start">С</Label>
            <Input
              id="target-start"
              type="date"
              value={start}
              onChange={(e) => {
                setStart(e.target.value);
                setPresetKey("custom");
              }}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="target-end">По</Label>
            <Input
              id="target-end"
              type="date"
              value={end}
              onChange={(e) => {
                setEnd(e.target.value);
                setPresetKey("custom");
              }}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="target-amount">Сумма, ₽</Label>
            <Input
              id="target-amount"
              inputMode="decimal"
              placeholder="5 000 000"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </div>
          <div className="flex flex-wrap items-center gap-3 sm:col-span-2 lg:col-span-6">
            <Button type="submit" size="sm" disabled={!amountValid || !start || !end || create.isPending}>
              {create.isPending ? "Сохранение…" : "Добавить цель"}
            </Button>
            {amount && !amountValid ? <span className="text-sm text-destructive">Введите сумму больше нуля.</span> : null}
            {create.isError ? <span className="text-sm text-destructive">{errorText(create.error)}</span> : null}
            {create.isSuccess && !amount ? <span className="text-sm text-muted-foreground">Цель добавлена.</span> : null}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

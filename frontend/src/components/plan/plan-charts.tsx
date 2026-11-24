"use client";

import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { METRIC_LABEL } from "@/components/plan/plan-progress-card";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useTargetSeries } from "@/hooks/queries";
import { formatDate, formatMoney } from "@/lib/format";
import type { TargetProgress } from "@/types/api";

const FACT_COLOR = "#0f766e";
const PLAN_COLOR = "#a8a29e";
const shortDate = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" });
const compact = new Intl.NumberFormat("ru-RU", { notation: "compact", maximumFractionDigits: 1 });

function dayLabel(iso: string) {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : shortDate.format(d).replace(".", "");
}

function targetTitle(p: TargetProgress) {
  return p.manager_id === null ? "Весь отдел" : (p.manager_name ?? `Менеджер #${p.manager_id}`);
}

/** Accumulated fact day by day against the even pace that ends exactly at the plan. */
export function TargetPaceChart({ targets }: { targets: TargetProgress[] }) {
  const [chosen, setChosen] = useState<number | null>(null);
  const current = targets.find((t) => t.target_id === chosen) ?? targets[0] ?? null;
  const series = useTargetSeries(current?.target_id ?? null);
  if (!current) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle className="text-base">Ход выполнения</CardTitle>
            <CardDescription>
              Факт нарастающим итогом {METRIC_LABEL[current.metric] ?? ""} и ровный темп до плана.
            </CardDescription>
          </div>
          {targets.length > 1 ? (
            <select
              aria-label="Чей план показать"
              className="h-9 rounded-lg border border-input bg-background px-2 text-sm"
              value={current.target_id}
              onChange={(e) => setChosen(Number(e.target.value))}
            >
              {targets.map((t) => (
                <option key={t.target_id} value={t.target_id}>
                  {targetTitle(t)}
                </option>
              ))}
            </select>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="h-72">
        {series.isLoading ? (
          <p className="text-sm text-muted-foreground">Загрузка…</p>
        ) : series.isError || !series.data ? (
          <p className="text-sm text-destructive">Не удалось загрузить график.</p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={series.data.points} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
              <XAxis dataKey="date" tickFormatter={dayLabel} tick={{ fontSize: 12 }} minTickGap={24} />
              <YAxis tickFormatter={(v) => compact.format(Number(v))} tick={{ fontSize: 12 }} width={48} />
              <Tooltip
                labelFormatter={(v) => formatDate(String(v))}
                formatter={(v) => formatMoney(Number(v), current.currency)}
              />
              <Legend verticalAlign="top" height={28} iconType="plainline" />
              <Line dataKey="pace" name="Темп до плана" stroke={PLAN_COLOR} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
              <Line dataKey="fact" name="Факт" stroke={FACT_COLOR} strokeWidth={2.5} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}

/** Plan and fact side by side for every manager who has a plan today. */
export function ManagersPlanChart({ items }: { items: TargetProgress[] }) {
  const data = [...items]
    .sort((a, b) => b.fact - a.fact)
    .map((p) => ({ name: targetTitle(p), plan: p.plan, fact: p.fact, currency: p.currency }));
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">План и факт по менеджерам</CardTitle>
        <CardDescription>Только менеджеры, которым поставлен план на сегодня.</CardDescription>
      </CardHeader>
      <CardContent style={{ height: Math.max(288, data.length * 56 + 64) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" barGap={2} barCategoryGap="24%" margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--border)" />
            <XAxis type="number" tickFormatter={(v) => compact.format(Number(v))} tick={{ fontSize: 12 }} />
            <YAxis type="category" dataKey="name" tick={{ fontSize: 12 }} width={132} />
            <Tooltip formatter={(v) => formatMoney(Number(v))} cursor={{ fill: "var(--muted)", opacity: 0.5 }} />
            <Legend verticalAlign="top" height={28} iconType="square" />
            <Bar dataKey="plan" name="План" fill={PLAN_COLOR} radius={[0, 3, 3, 0]} isAnimationActive={false} />
            <Bar dataKey="fact" name="Факт" fill={FACT_COLOR} radius={[0, 3, 3, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

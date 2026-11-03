import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate, formatMoney, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { PlanStatus, TargetProgress } from "@/types/api";

export const PLAN_STATUS: Record<PlanStatus, { label: string; variant: "success" | "warning" | "destructive" | "secondary"; bar: string }> = {
  done: { label: "Выполнен", variant: "success", bar: "bg-emerald-600" },
  on_track: { label: "В графике", variant: "success", bar: "bg-emerald-600" },
  at_risk: { label: "Под угрозой", variant: "warning", bar: "bg-amber-500" },
  behind: { label: "Отстаём", variant: "destructive", bar: "bg-red-600" },
  missed: { label: "Не выполнен", variant: "destructive", bar: "bg-red-600" },
  not_started: { label: "Не начался", variant: "secondary", bar: "bg-muted-foreground" },
  early: { label: "Начало периода", variant: "secondary", bar: "bg-primary" },
};

function forecastText(p: TargetProgress): string {
  return p.forecast_reliable
    ? `${formatMoney(p.forecast, p.currency)} (${formatPercent(p.forecast_percent)})`
    : `появится через ${p.forecast_in_days} дн.`;
}

/** Fact bar with a tick where the plan "should" be today if sales were spread evenly. */
export function PlanBar({ p, className }: { p: TargetProgress; className?: string }) {
  const factPct = Math.min(100, p.percent);
  const expectedPct = p.plan > 0 ? Math.min(100, (p.expected / p.plan) * 100) : 0;
  return (
    <div
      className={cn("relative h-3 w-full overflow-hidden rounded-full bg-muted", className)}
      role="progressbar"
      aria-valuenow={p.percent}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`Выполнено ${formatPercent(p.percent)}`}
    >
      <div className={cn("h-full rounded-full", PLAN_STATUS[p.status].bar)} style={{ width: `${factPct}%` }} />
      {p.active && p.status !== "done" ? (
        <div
          className="absolute inset-y-0 w-0.5 bg-foreground/60"
          style={{ left: `${expectedPct}%` }}
          title={`Ожидалось к сегодняшнему дню: ${formatMoney(p.expected, p.currency)}`}
        />
      ) : null}
    </div>
  );
}

export function PlanProgressCard({ p, compact = false }: { p: TargetProgress; compact?: boolean }) {
  const s = PLAN_STATUS[p.status];
  const title = p.manager_id === null ? "План отдела" : (p.manager_name ?? `Менеджер #${p.manager_id}`);
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="text-base">
              {p.manager_id !== null ? <Link href={`/managers/${p.manager_id}`} className="hover:underline">{title}</Link> : title}
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              {formatDate(p.period_start)} — {formatDate(p.period_end)}
            </p>
          </div>
          <Badge variant={s.variant} className="shrink-0 whitespace-nowrap">
            {s.label}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div className="flex items-baseline justify-between gap-2">
          <span className="font-serif text-2xl font-semibold">{formatPercent(p.percent)}</span>
          <span className="text-muted-foreground">
            {formatMoney(p.fact, p.currency)} из {formatMoney(p.plan, p.currency)}
          </span>
        </div>
        <PlanBar p={p} />
        {!compact ? (
          <div className="grid gap-x-4 gap-y-1 pt-1 text-muted-foreground sm:grid-cols-2">
            <span>Прогноз: {forecastText(p)}</span>
            <span>Сделок выиграно: {p.won_count}</span>
            <span>Осталось: {formatMoney(p.remaining, p.currency)}</span>
            <span>Дней осталось: {p.days_left}</span>
            {p.per_day_needed ? (
              <span className="sm:col-span-2">Нужно в день: {formatMoney(p.per_day_needed, p.currency)}</span>
            ) : null}
          </div>
        ) : (
          <p className="text-muted-foreground">
            Прогноз {p.forecast_reliable ? formatPercent(p.forecast_percent) : forecastText(p)} · осталось {p.days_left} дн.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

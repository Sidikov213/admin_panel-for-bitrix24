"use client";

import { cn } from "@/lib/utils";

export type MetricDelta = {
  current?: number;
  previous?: number;
  abs_delta?: number;
  pct_delta?: number | null;
};

export function DeltaBadge({
  delta,
  className,
  suffix = "",
  compact = false,
}: {
  delta?: MetricDelta | null;
  className?: string;
  suffix?: string;
  compact?: boolean;
}) {
  if (!delta || delta.abs_delta === undefined || delta.abs_delta === null) return null;
  const abs = delta.abs_delta;
  if (abs === 0 && (delta.pct_delta === 0 || delta.pct_delta == null)) {
    return <span className={cn("text-[12px] text-muted-foreground", className)}>без изменений</span>;
  }
  const positive = abs > 0;
  const sign = positive ? "+" : "";
  const pct =
    delta.pct_delta === null || delta.pct_delta === undefined
      ? null
      : `${sign}${delta.pct_delta}%`;

  if (compact && pct != null) {
    return (
      <span
        className={cn(
          "text-[12px] font-medium tabular-nums",
          positive ? "text-[var(--success)]" : abs < 0 ? "text-destructive" : "text-muted-foreground",
          className,
        )}
      >
        {pct} к прошлому периоду
      </span>
    );
  }

  return (
    <span
      className={cn(
        "text-[12px] font-medium tabular-nums",
        positive ? "text-[var(--success)]" : abs < 0 ? "text-destructive" : "text-muted-foreground",
        className,
      )}
    >
      {sign}
      {typeof abs === "number" && !Number.isInteger(abs) ? abs.toLocaleString("ru-RU") : abs}
      {suffix}
      {pct ? ` · ${pct}` : ""}
    </span>
  );
}

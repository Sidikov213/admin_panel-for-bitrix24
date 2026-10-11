"use client";

import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export type Freshness = {
  last_updated_at?: string | null;
  age_minutes?: number | null;
  is_stale?: boolean;
  sync_failed?: boolean;
  warning?: string | null;
};

export function DataFreshness({
  freshness,
  fallbackAt,
  className,
  compact = false,
}: {
  freshness?: Freshness | null;
  fallbackAt?: string | null;
  className?: string;
  compact?: boolean;
}) {
  const at = freshness?.last_updated_at || fallbackAt;
  const stale = Boolean(freshness?.is_stale || freshness?.sync_failed);
  const warning = freshness?.warning;

  if (compact) {
    return (
      <div className={cn("flex items-center gap-2 text-[12px] text-muted-foreground", className)}>
        <span className="tabular-nums">{formatDateTime(at) || "—"}</span>
        {freshness?.sync_failed ? (
          <span className="text-[11px] font-medium text-destructive">ошибка sync</span>
        ) : stale && warning ? (
          <span className="text-[11px] font-medium text-[var(--warning)]">устарело</span>
        ) : (
          <span className="text-[11px] text-muted-foreground/80">актуально</span>
        )}
      </div>
    );
  }

  return (
    <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted-foreground", className)}>
      <span>
        Обновлено{" "}
        <span className="font-medium tabular-nums text-foreground">{formatDateTime(at) || "—"}</span>
      </span>
      {freshness?.sync_failed ? (
        <span className="text-[12px] font-medium text-destructive">Ошибка синхронизации</span>
      ) : null}
      {stale && warning ? (
        <span className="text-[12px] font-medium text-[var(--warning)]">{warning}</span>
      ) : null}
      {!stale ? <span className="text-[12px] text-muted-foreground/80">Данные актуальны</span> : null}
    </div>
  );
}

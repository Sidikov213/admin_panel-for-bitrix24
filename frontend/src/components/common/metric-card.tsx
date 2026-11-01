"use client";

import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Sparkline } from "@/components/charts/sparkline";

export function MetricCard({
  label,
  value,
  icon: Icon,
  tone,
  series,
  chart = "area",
  footer,
}: {
  label: string;
  value: string;
  icon: LucideIcon;
  tone: { bg: string; fg: string };
  series?: number[];
  chart?: "area" | "bar";
  footer?: ReactNode;
}) {
  return (
    <article className="panel flex h-full min-h-[148px] flex-col p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[13px] font-medium text-muted-foreground">{label}</p>
        <span
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[12px]"
          style={{ background: tone.bg, color: tone.fg }}
        >
          <Icon className="h-4 w-4" strokeWidth={1.75} />
        </span>
      </div>
      <p className="kpi-value mt-3 text-[1.65rem]">{value}</p>
      <div className="mt-1 min-h-[18px] text-[12px]">{footer}</div>
      <div className="mt-auto pt-1">
        <Sparkline data={series ?? []} color={tone.fg} variant={chart} />
      </div>
    </article>
  );
}

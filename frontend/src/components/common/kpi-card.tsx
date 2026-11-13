"use client";

import Link from "next/link";
import { ArrowDownRight, ArrowUpRight, ChevronRight, Info } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { MetricDelta } from "@/types/api";

type KpiCardProps = {
  title: string;
  value: string;
  href?: string;
  hint?: string;
  source?: string;
  formula?: string;
  freshness?: string;
  className?: string;
  /** Change vs the previous period of the same length */
  delta?: MetricDelta | null;
  /** Whether growth is good news (won) or bad news (lost) */
  higherIsBetter?: boolean;
  formatPrevious?: (v: number) => string;
};

export function DeltaLine({ delta, higherIsBetter = true, formatPrevious }: { delta: MetricDelta; higherIsBetter?: boolean; formatPrevious?: (v: number) => string }) {
  const prev = formatPrevious ? formatPrevious(delta.previous) : formatNumber(delta.previous);
  if (delta.delta === 0) {
    return <p className="mt-1 text-[13px] text-muted-foreground">Как в прошлом периоде ({prev})</p>;
  }
  const up = delta.delta > 0;
  // From a small base a percentage only scares: 6 → 30 is "+400 %". Show the old value instead.
  const pct = delta.delta_pct !== null && Math.abs(delta.previous) >= 10 ? delta.delta_pct : null;
  const good = up === higherIsBetter;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <p className={cn("mt-1 flex items-center gap-1 text-[13px]", good ? "text-emerald-700" : "text-red-700")}>
      <Icon className="h-3.5 w-3.5" aria-hidden />
      <span>
        {pct !== null ? `${up ? "+" : ""}${formatPercent(pct)}` : up ? "рост" : "снижение"}
        <span className="text-muted-foreground"> · было {prev}</span>
      </span>
    </p>
  );
}

export function KpiCard({
  title,
  value,
  href,
  hint,
  source,
  formula,
  freshness,
  className,
  delta,
  higherIsBetter,
  formatPrevious,
}: KpiCardProps) {
  const meta = [
    source && `Источник: ${source}`,
    formula && `Формула: ${formula}`,
    freshness && `Актуальность: ${freshness}`,
    hint,
  ]
    .filter(Boolean)
    .join(" · ");

  const inner = (
    <Card
      className={cn(
        "relative overflow-hidden transition-shadow",
        href && "hover:shadow-md hover:border-primary/30 cursor-pointer",
        className,
      )}
    >
      <CardHeader className="p-5 pb-1.5">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="font-sans text-sm font-medium text-muted-foreground">{title}</CardTitle>
          <span className="flex shrink-0 items-center gap-1 text-muted-foreground">
            {meta ? (
              <span title={meta}>
                <Info className="h-3.5 w-3.5" />
              </span>
            ) : null}
            {href ? <ChevronRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5 group-hover:text-primary" aria-hidden /> : null}
          </span>
        </div>
      </CardHeader>
      <CardContent className="p-5 pt-0">
        <p className="font-serif text-3xl font-semibold tabular-nums tracking-tight">{value}</p>
        {delta ? <DeltaLine delta={delta} higherIsBetter={higherIsBetter} formatPrevious={formatPrevious} /> : null}
      </CardContent>
    </Card>
  );

  if (href)
    return (
      <Link href={href} className="group block" title="Открыть список сделок">
        {inner}
      </Link>
    );
  return inner;
}

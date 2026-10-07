"use client";

import Link from "next/link";
import { Info } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type KpiCardProps = {
  title: string;
  value: string;
  href?: string;
  hint?: string;
  source?: string;
  formula?: string;
  freshness?: string;
  className?: string;
};

export function KpiCard({ title, value, href, hint, source, formula, freshness, className }: KpiCardProps) {
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
      <div className="absolute inset-y-0 left-0 w-1 bg-accent" />
      <CardHeader className="pb-2 pl-7">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
          {meta ? (
            <span title={meta} className="text-muted-foreground">
              <Info className="h-3.5 w-3.5" />
            </span>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="pl-7">
        <p className="font-serif text-3xl font-semibold tracking-tight">{value}</p>
      </CardContent>
    </Card>
  );

  if (href) return <Link href={href}>{inner}</Link>;
  return inner;
}

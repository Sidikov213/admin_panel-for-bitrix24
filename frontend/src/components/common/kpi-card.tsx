"use client";

import type { ReactNode } from "react";
import Link from "next/link";
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
  footer?: ReactNode;
  /** Compact strip metric — no card chrome */
  variant?: "card" | "strip";
};

/** Dense metric cell. Prefer strip; card only when a surface is truly needed. */
export function KpiCard({
  title,
  value,
  href,
  hint,
  className,
  footer,
  variant = "strip",
}: KpiCardProps) {
  const body = (
    <div
      className={cn(
        variant === "card" && "rounded-[var(--radius)] border border-border bg-card px-3.5 py-3",
        variant === "strip" && "min-w-0",
        href && "transition-colors duration-150 hover:bg-muted/50 rounded-md",
        className,
      )}
      title={hint}
    >
      <p className="text-[12px] font-medium text-muted-foreground">{title}</p>
      <p className="kpi-value mt-1 text-[1.625rem]">{value}</p>
      {footer ? <div className="mt-1.5">{footer}</div> : null}
    </div>
  );

  if (href) return <Link href={href}>{body}</Link>;
  return body;
}

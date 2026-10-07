"use client";

import * as React from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

interface SheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
  side?: "left" | "right";
}

export function Sheet({ open, onOpenChange, children, side = "left" }: SheetProps) {
  React.useEffect(() => {
    if (open) document.body.style.overflow = "hidden";
    else document.body.style.overflow = "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50">
      <button
        type="button"
        aria-label="Закрыть меню"
        className="absolute inset-0 bg-black/40"
        onClick={() => onOpenChange(false)}
      />
      <div
        className={cn(
          "absolute top-0 h-full w-[min(100%,18rem)] border-border bg-background shadow-xl",
          side === "left" ? "left-0 border-r" : "right-0 border-l",
        )}
      >
        {children}
      </div>
    </div>
  );
}

export function SheetHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex items-center justify-between border-b border-border p-4", className)} {...props} />;
}

export function SheetClose({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="rounded-md p-1 hover:bg-muted" aria-label="Закрыть">
      <X className="h-5 w-5" />
    </button>
  );
}

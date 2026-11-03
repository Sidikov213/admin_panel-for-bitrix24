"use client";

import { Label } from "@/components/ui/label";
import { useManagers, usePipelines } from "@/hooks/queries";
import { managerName } from "@/lib/format";

export const selectClass =
  "flex h-10 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** Pipeline (Bitrix CATEGORY_ID) and manager selects shared by the control pages. */
export function ScopeFilters({
  categoryId,
  managerId,
  onCategory,
  onManager,
  idPrefix,
}: {
  categoryId?: number;
  managerId?: number;
  onCategory: (v: number | undefined) => void;
  onManager: (v: number | undefined) => void;
  idPrefix: string;
}) {
  const pipelines = usePipelines();
  const managers = useManagers();
  const sorted = (managers.data ?? []).slice().sort((a, b) => managerName(a).localeCompare(managerName(b)));
  return (
    <>
      <div className="w-full space-y-1.5 sm:w-48">
        <Label htmlFor={`${idPrefix}-pipeline`} className="block text-xs text-muted-foreground">
          Воронка
        </Label>
        <select
          id={`${idPrefix}-pipeline`}
          className={selectClass}
          value={categoryId ?? ""}
          onChange={(e) => onCategory(e.target.value ? Number(e.target.value) : undefined)}
        >
          <option value="">Все воронки</option>
          {(pipelines.data ?? []).map((p) => (
            <option key={p.id} value={String(p.bitrix_id)}>
              {p.name}
            </option>
          ))}
        </select>
      </div>
      <div className="w-full space-y-1.5 sm:w-52">
        <Label htmlFor={`${idPrefix}-manager`} className="block text-xs text-muted-foreground">
          Менеджер
        </Label>
        <select
          id={`${idPrefix}-manager`}
          className={selectClass}
          value={managerId ?? ""}
          onChange={(e) => onManager(e.target.value ? Number(e.target.value) : undefined)}
        >
          <option value="">Все менеджеры</option>
          {sorted.map((m) => (
            <option key={m.id} value={m.id}>
              {managerName(m)}
            </option>
          ))}
        </select>
      </div>
    </>
  );
}

/** «Открыть в Bitrix» — opens the deal card in the CRM in a new tab. */
export function BitrixLink({ href }: { href: string | null | undefined }) {
  if (!href) return null;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="whitespace-nowrap text-xs text-primary hover:underline">
      Открыть в Bitrix ↗
    </a>
  );
}

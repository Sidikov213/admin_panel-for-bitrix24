"use client";

import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export type PeriodPreset =
  | "today"
  | "yesterday"
  | "last_7_days"
  | "current_week"
  | "previous_week"
  | "current_month"
  | "previous_month"
  | "custom";

export type PeriodValue = {
  preset: PeriodPreset;
  from: string;
  to: string;
};

function pad(n: number) {
  return String(n).padStart(2, "0");
}

/** Local calendar date YYYY-MM-DD (avoids UTC shift from toISOString). */
export function isoLocalDate(d: Date) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function startOfWeek(d: Date) {
  const x = new Date(d);
  const day = (x.getDay() + 6) % 7; // Monday=0
  x.setDate(x.getDate() - day);
  x.setHours(0, 0, 0, 0);
  return x;
}

export function periodFromPreset(preset: PeriodPreset): Pick<PeriodValue, "from" | "to"> {
  const today = new Date();
  today.setHours(12, 0, 0, 0);

  if (preset === "today") {
    const s = isoLocalDate(today);
    return { from: s, to: s };
  }
  if (preset === "yesterday") {
    const y = new Date(today);
    y.setDate(y.getDate() - 1);
    const s = isoLocalDate(y);
    return { from: s, to: s };
  }
  if (preset === "last_7_days") {
    const from = new Date(today);
    from.setDate(from.getDate() - 6);
    return { from: isoLocalDate(from), to: isoLocalDate(today) };
  }
  if (preset === "current_week") {
    const start = startOfWeek(today);
    return { from: isoLocalDate(start), to: isoLocalDate(today) };
  }
  if (preset === "previous_week") {
    const start = startOfWeek(today);
    start.setDate(start.getDate() - 7);
    const end = new Date(start);
    end.setDate(end.getDate() + 6);
    return { from: isoLocalDate(start), to: isoLocalDate(end) };
  }
  if (preset === "current_month") {
    const start = new Date(today.getFullYear(), today.getMonth(), 1);
    return { from: isoLocalDate(start), to: isoLocalDate(today) };
  }
  if (preset === "previous_month") {
    const start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    const end = new Date(today.getFullYear(), today.getMonth(), 0);
    return { from: isoLocalDate(start), to: isoLocalDate(end) };
  }
  const from = new Date(today);
  from.setDate(from.getDate() - 6);
  return { from: isoLocalDate(from), to: isoLocalDate(today) };
}

export function defaultPeriod(): PeriodValue {
  return { preset: "current_week", ...periodFromPreset("current_week") };
}

const LABELS: Record<PeriodPreset, string> = {
  today: "Сегодня",
  yesterday: "Вчера",
  last_7_days: "7 дней",
  current_week: "Текущая неделя",
  previous_week: "Предыдущая неделя",
  current_month: "Текущий месяц",
  previous_month: "Предыдущий месяц",
  custom: "Свой период",
};

export function PeriodPicker({
  value,
  onChange,
  compact = false,
}: {
  value: PeriodValue;
  onChange: (v: PeriodValue) => void;
  compact?: boolean;
}) {
  return (
    <div className={`flex flex-wrap items-center gap-2 ${compact ? "" : "gap-3"}`}>
      <Select
        value={value.preset}
        onValueChange={(preset) => {
          const p = preset as PeriodPreset;
          if (p === "custom") onChange({ ...value, preset: p });
          else onChange({ preset: p, ...periodFromPreset(p) });
        }}
      >
        <SelectTrigger className={compact ? "h-8 w-[9.5rem] text-[13px]" : "w-52"}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(Object.keys(LABELS) as PeriodPreset[]).map((key) => (
            <SelectItem key={key} value={key}>
              {LABELS[key]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {value.preset === "custom" ? (
        <>
          <Input
            type="date"
            className="h-8 w-[9.5rem] text-[13px]"
            value={value.from}
            onChange={(e) => onChange({ ...value, from: e.target.value })}
          />
          <Input
            type="date"
            className="h-8 w-[9.5rem] text-[13px]"
            value={value.to}
            onChange={(e) => onChange({ ...value, to: e.target.value })}
          />
        </>
      ) : null}
    </div>
  );
}

"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export type PeriodPreset = "week" | "month" | "custom";

export type PeriodValue = {
  preset: PeriodPreset;
  from: string;
  to: string;
};

function isoDate(d: Date) {
  return d.toISOString().slice(0, 10);
}

export function defaultPeriod(): PeriodValue {
  const to = new Date();
  const from = new Date();
  from.setDate(to.getDate() - 30);
  return { preset: "month", from: isoDate(from), to: isoDate(to) };
}

export function periodFromPreset(preset: PeriodPreset): Pick<PeriodValue, "from" | "to"> {
  const to = new Date();
  const from = new Date();
  if (preset === "week") from.setDate(to.getDate() - 7);
  else if (preset === "month") from.setDate(to.getDate() - 30);
  return { from: isoDate(from), to: isoDate(to) };
}

export function PeriodPicker({
  value,
  onChange,
}: {
  value: PeriodValue;
  onChange: (v: PeriodValue) => void;
}) {
  return (
    <div className="flex flex-wrap items-end gap-3">
      <div className="w-40">
        <Label className="mb-1.5 block text-xs text-muted-foreground">Период</Label>
        <Select
          value={value.preset}
          onValueChange={(preset) => {
            const p = preset as PeriodPreset;
            if (p === "custom") onChange({ ...value, preset: p });
            else onChange({ preset: p, ...periodFromPreset(p) });
          }}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="week">7 дней</SelectItem>
            <SelectItem value="month">30 дней</SelectItem>
            <SelectItem value="custom">Свой период</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {value.preset === "custom" ? (
        <>
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">С</Label>
            <Input
              type="date"
              value={value.from}
              onChange={(e) => onChange({ ...value, from: e.target.value })}
            />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">По</Label>
            <Input type="date" value={value.to} onChange={(e) => onChange({ ...value, to: e.target.value })} />
          </div>
        </>
      ) : null}
    </div>
  );
}

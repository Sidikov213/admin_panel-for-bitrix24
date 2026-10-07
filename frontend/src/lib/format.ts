const dateTimeFmt = new Intl.DateTimeFormat("ru-RU", {
  dateStyle: "medium",
  timeStyle: "short",
});

const dateFmt = new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium" });

const numberFmt = new Intl.NumberFormat("ru-RU");

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return dateTimeFmt.format(d);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return dateFmt.format(d);
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "0";
  return numberFmt.format(value);
}

export function formatMoney(value: number | string | null | undefined, currency = "RUB"): string {
  if (value === null || value === undefined || value === "") return "—";
  const num = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(num)) return String(value);
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(num);
}

export function managerName(m: { name: string; last_name: string } | null | undefined): string {
  if (!m) return "Не назначен";
  return `${m.last_name} ${m.name}`.trim();
}

export function syncStateAt(value: string | { at?: string } | null | undefined): string | null {
  if (!value) return null;
  if (typeof value === "string") return value;
  return value.at ?? null;
}

/** Format Bitrix / ISO timestamps for Manager Control UI (local display). */

export function formatTimeHm(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

export function formatDateShort(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  const d = new Date(`${isoDate}T12:00:00`);
  if (Number.isNaN(d.getTime())) return isoDate;
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "short", weekday: "short" });
}

export function statusTone(normalized: string | null | undefined): string {
  switch (normalized) {
    case "working":
      return "text-[var(--primary)]";
    case "paused":
      return "text-[var(--warning,#b45309)]";
    case "closed":
      return "text-foreground";
    case "stale_unclosed":
      return "text-[var(--warning,#b45309)]";
    case "not_started":
    case "no_data":
    case "unknown_bitrix":
      return "text-muted-foreground";
    default:
      return "text-muted-foreground";
  }
}

/** Shared category-axis tick for charts with long Russian labels. */

export const CATEGORY_AXIS_WIDTH = 188;
export const CATEGORY_LABEL_WIDTH = 176;

const FONT_SIZE = 13;
const CHAR_PX = 7.2;

/** Height grows with the number of categories so 2-line ticks do not collide. */
export function categoryChartHeight(count: number): number {
  const rows = Math.max(count, 1);
  return Math.max(220, rows * 44 + 36);
}

function ellipsisAtWord(text: string, maxChars: number): string {
  const budget = Math.max(1, maxChars - 1);
  if (text.length <= budget) return text;
  let cut = text.slice(0, budget);
  const space = cut.lastIndexOf(" ");
  if (space >= Math.floor(budget * 0.45)) cut = cut.slice(0, space);
  return cut.replace(/[\s,;:–—-]+$/u, "") + "…";
}

/** At most two lines. Breaks on spaces and appends … when the remainder does not fit. */
export function splitAxisLabel(text: string, maxWidthPx: number, maxLines = 2): string[] {
  const full = text.trim();
  if (!full) return [""];
  const maxChars = Math.max(10, Math.floor(maxWidthPx / CHAR_PX));
  if (full.length <= maxChars) return [full];

  const words = full.split(/\s+/);
  const lines: string[] = [];
  let current = "";

  for (let i = 0; i < words.length; i++) {
    const word = words[i] ?? "";
    const next = current ? `${current} ${word}` : word;
    if (next.length <= maxChars) {
      current = next;
      continue;
    }
    if (!current) {
      return [ellipsisAtWord(full, maxChars)];
    }
    lines.push(current);
    current = "";
    if (lines.length === maxLines - 1) {
      lines.push(ellipsisAtWord(words.slice(i).join(" "), maxChars));
      return lines;
    }
    i -= 1;
  }
  if (current) lines.push(current);
  return lines.slice(0, maxLines);
}

type TooltipRow = { name?: string; value?: number | string; color?: string };

export function CategoryBarTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipRow[];
  label?: string | number;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0];
  return (
    <div
      style={{
        borderRadius: 14,
        border: "1px solid var(--border)",
        background: "var(--card, #fff)",
        fontSize: 13,
        lineHeight: 1.35,
        padding: "8px 10px",
        maxWidth: 280,
        whiteSpace: "normal",
      }}
    >
      <div style={{ marginBottom: 4 }}>{label}</div>
      <div>
        {row?.name ?? "Значение"}: {row?.value ?? "—"}
      </div>
    </div>
  );
}

type TickProps = {
  x?: number;
  y?: number;
  payload?: { value?: string | number };
  maxWidth?: number;
};

export function CategoryAxisTick({ x = 0, y = 0, payload, maxWidth = CATEGORY_LABEL_WIDTH }: TickProps) {
  const full = String(payload?.value ?? "");
  const lines = splitAxisLabel(full, maxWidth);
  const lineHeight = 16;
  const start = -((lines.length - 1) * lineHeight) / 2;

  return (
    <g transform={`translate(${x},${y})`}>
      <title>{full}</title>
      {lines.map((line, index) => (
        <text
          key={`${line}-${index}`}
          x={-6}
          y={start + index * lineHeight}
          dy="0.32em"
          textAnchor="end"
          fill="var(--muted-foreground)"
          fontSize={FONT_SIZE}
        >
          {line}
        </text>
      ))}
    </g>
  );
}

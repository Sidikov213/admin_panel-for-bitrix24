"use client";

import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDeal } from "@/hooks/queries";
import { bitrixDealUrl } from "@/lib/bitrix-url";
import { formatDateTime, formatMoney, managerName } from "@/lib/format";

export function DealDetailView({ id }: { id: number }) {
  const deal = useDeal(id);

  if (deal.isLoading) return <PageLoading rows={2} />;
  if (deal.isError || !deal.data) {
    return <ErrorState message="Сделка не найдена или ошибка загрузки." onRetry={() => void deal.refetch()} />;
  }

  const d = deal.data;
  const bitrixUrl = d.bitrix_url || bitrixDealUrl(d.bitrix_id);
  const timeline = d.timeline?.length ? d.timeline : null;
  const activeViolations = d.violations?.active ?? [];
  const warnings: string[] = [];
  if (d.no_future_activity_label) warnings.push(d.no_future_activity_label);
  if (d.hours_without_observed_movement != null) {
    warnings.push(`Без движения ~${d.hours_without_observed_movement} ч`);
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 border-b border-border pb-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <Link href="/deals" className="text-[12px] text-muted-foreground hover:text-foreground">
            ← Сделки
          </Link>
          <h1 className="page-title mt-1 text-[1.5rem] sm:text-[1.75rem]">{d.title}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
            <span className="text-[1.25rem] font-semibold tabular-nums">
              {formatMoney(d.opportunity, d.currency_id ?? "RUB")}
            </span>
            <span className="text-muted-foreground">{d.stage?.name ?? "—"}</span>
            <span>{managerName(d.assigned_manager)}</span>
            {d.closed ? (
              <Badge variant="secondary">Закрыта</Badge>
            ) : (
              <Badge variant="success">Активна</Badge>
            )}
          </div>
        </div>
        {bitrixUrl ? (
          <a
            href={bitrixUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-[13px] font-medium transition-colors hover:bg-muted"
          >
            Bitrix
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        ) : null}
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.7fr)_minmax(240px,0.9fr)]">
        {/* Timeline — primary */}
        <section>
          <h2 className="section-title mb-3">Timeline</h2>
          <p className="meta mb-4">
            observed_at — время обнаружения при синхронизации, не всегда точное время в Bitrix
          </p>
          {!(timeline || d.change_events.length) ? (
            <EmptyState title="История пуста" />
          ) : (
            <ul className="space-y-0">
              {timeline
                ? timeline.map((t, idx) => (
                    <li key={`${t.at}-${idx}`} className="relative border-l border-border py-3 pl-4 first:pt-0">
                      <span className="absolute -left-[3px] top-4 h-1.5 w-1.5 rounded-full bg-primary" />
                      <p className="meta tabular-nums">{formatDateTime(t.at)}</p>
                      <p className="mt-0.5 text-[13px] font-medium">{t.title}</p>
                      <p className="text-[13px] text-muted-foreground">{t.detail}</p>
                      {t.is_observed && t.note ? (
                        <p className="mt-1 text-[12px] text-[var(--warning)]">{t.note}</p>
                      ) : null}
                    </li>
                  ))
                : d.change_events.map((c) => (
                    <li
                      key={c.id ?? `${c.field_name}-${c.observed_at}`}
                      className="relative border-l border-border py-3 pl-4 first:pt-0"
                    >
                      <span className="absolute -left-[3px] top-4 h-1.5 w-1.5 rounded-full bg-primary" />
                      <p className="meta tabular-nums">{formatDateTime(c.observed_at)}</p>
                      <p className="mt-0.5 text-[13px] font-medium">{c.field_name}</p>
                      <p className="text-[13px] text-muted-foreground">
                        {c.old_value ?? "—"} → {c.new_value ?? "—"}
                      </p>
                      {c.note ? <p className="mt-1 text-[12px] text-[var(--warning)]">{c.note}</p> : null}
                    </li>
                  ))}
            </ul>
          )}
        </section>

        {/* Right sidebar */}
        <aside className="space-y-5">
          <section className="panel panel-pad space-y-2.5 text-[13px]">
            <h2 className="section-title">Статус</h2>
            <Row label="Bitrix ID" value={String(d.bitrix_id)} />
            <Row label="Воронка" value={String(d.pipeline_name ?? d.category_id ?? "—")} />
            <Row label="Этап" value={d.stage?.name ?? "—"} />
            <Row label="Менеджер" value={managerName(d.assigned_manager)} />
            <Row label="Создана" value={formatDateTime(d.date_create) || "—"} />
            <Row label="Изменена" value={formatDateTime(d.date_modify) || "—"} />
            <Row label="Открытых дел" value={String(d.open_activities_count ?? 0)} />
            <Row label="Ближ. дедлайн" value={formatDateTime(d.next_deadline_at) || "—"} />
          </section>

          {warnings.length ? (
            <section className="panel panel-pad">
              <h2 className="section-title mb-2">Предупреждения</h2>
              <ul className="space-y-1.5 text-[13px] text-[var(--warning)]">
                {warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </section>
          ) : null}

          <section className="panel panel-pad">
            <h2 className="section-title mb-2">Дела</h2>
            <ActivityBlock title="Открытые" items={d.current_activities ?? d.activities.filter((a) => !a.completed)} />
            <ActivityBlock title="Просроченные" items={d.overdue_activities ?? []} />
            <ActivityBlock title="Будущие" items={d.future_activities ?? []} />
          </section>

          <section className="panel panel-pad">
            <h2 className="section-title mb-2">Нарушения</h2>
            {!activeViolations.length && !(d.violations?.resolved?.length) ? (
              <p className="text-[13px] text-muted-foreground">Нет открытых нарушений</p>
            ) : (
              <div className="space-y-2">
                {activeViolations.map((v) => (
                  <div key={v.id} className="border-b border-border pb-2 last:border-0 last:pb-0">
                    <p className="text-[13px] font-medium">{v.rule_name}</p>
                    <p className="text-[12px] text-muted-foreground">{v.details}</p>
                    <p className="meta mt-0.5">
                      {v.severity} · {formatDateTime(v.detected_at)}
                    </p>
                  </div>
                ))}
                {(d.violations?.resolved?.length ?? 0) > 0 ? (
                  <p className="meta pt-1">Resolved: {d.violations!.resolved.length}</p>
                ) : null}
              </div>
            )}
          </section>
        </aside>
      </div>

      {(d.snapshots?.length ?? 0) > 0 ? (
        <section className="panel overflow-hidden">
          <div className="border-b border-border px-4 py-3">
            <h2 className="section-title">Snapshots</h2>
          </div>
          <Table className="data-table">
            <TableHeader>
              <TableRow>
                <TableHead className="pl-4">Observed</TableHead>
                <TableHead>Hash</TableHead>
                <TableHead className="pr-4">Summary</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {d.snapshots!.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="pl-4 text-[12px]">{formatDateTime(s.observed_at)}</TableCell>
                  <TableCell className="font-mono text-[11px]">{s.content_hash.slice(0, 10)}…</TableCell>
                  <TableCell className="pr-4 text-[12px] text-muted-foreground">
                    {s.payload_summary ? JSON.stringify(s.payload_summary) : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      ) : null}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="truncate text-right tabular-nums">{value}</span>
    </div>
  );
}

function ActivityBlock({
  title,
  items,
}: {
  title: string;
  items: Array<{ id: number; bitrix_id?: number; subject?: string | null; deadline?: string | null }>;
}) {
  return (
    <div className="mb-3 last:mb-0">
      <p className="meta mb-1">{title}</p>
      {!items.length ? (
        <p className="text-[12px] text-muted-foreground">Нет</p>
      ) : (
        <ul className="space-y-1.5">
          {items.slice(0, 6).map((a) => (
            <li key={a.id}>
              <p className="text-[13px] font-medium leading-snug">{a.subject || `Дело #${a.bitrix_id}`}</p>
              <p className="meta tabular-nums">{formatDateTime(a.deadline) || "—"}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ErrorState, PageLoading } from "@/components/common/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, type SalesRule, type SalesRulePreview } from "@/lib/api";
import { formatMoney, formatNumber } from "@/lib/format";
import { getBoolActiveLabel, getEnabledLabel, getSeverityLabel } from "@/lib/ui-labels";
import { cn } from "@/lib/utils";

const emptyForm: Partial<SalesRule> = {
  rule_name: "",
  description: "",
  enabled: false,
  severity: "medium",
  future_activity_required: null,
  overdue_activity_allowed: null,
  max_idle_minutes: null,
  max_stage_duration_minutes: null,
  max_next_activity_minutes: null,
  pipeline_bitrix_id: null,
  stage_id: null,
  required_fields: [],
};

export default function SalesRulesAdminPage() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["sales-rules"], queryFn: () => api.salesRules() });
  const fields = useQuery({ queryKey: ["deal-fields"], queryFn: () => api.dealFields() });
  const [form, setForm] = useState<Partial<SalesRule>>(emptyForm);
  const [editId, setEditId] = useState<number | null>(null);
  const [preview, setPreview] = useState<SalesRulePreview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: async () => {
      if (editId) return api.updateSalesRule(editId, form);
      return api.createSalesRule(form);
    },
    onSuccess: async () => {
      setForm(emptyForm);
      setEditId(null);
      setPreview(null);
      await qc.invalidateQueries({ queryKey: ["sales-rules"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const previewMut = useMutation({
    mutationFn: () => api.previewSalesRule(form),
    onSuccess: (data) => setPreview(data),
    onError: (e: Error) => setError(e.message),
  });

  const del = useMutation({
    mutationFn: (id: number) => api.deleteSalesRule(id),
    onSuccess: async () => qc.invalidateQueries({ queryKey: ["sales-rules"] }),
  });

  const syncFields = useMutation({
    mutationFn: () => api.syncDealFields(),
    onSuccess: async () => qc.invalidateQueries({ queryKey: ["deal-fields"] }),
  });

  const evaluate = useMutation({
    mutationFn: () => api.evaluateSalesRules(),
  });

  const human = useMemo(() => preview?.human_description, [preview]);

  if (list.isLoading) return <PageLoading rows={5} />;
  if (list.isError) return <ErrorState message="Не удалось загрузить правила." onRetry={() => void list.refetch()} />;

  function loadRule(r: SalesRule) {
    setEditId(r.id ?? null);
    setForm({ ...r });
    setPreview(null);
    setError(null);
  }

  const items = list.data?.items ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-muted-foreground">
          {list.data?.total ?? 0} правил · {getEnabledLabel(true).toLowerCase()}{" "}
          {items.filter((i) => i.enabled).length}
        </p>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setEditId(null);
              setForm(emptyForm);
              setPreview(null);
            }}
          >
            Новое правило
          </Button>
          <Button type="button" variant="secondary" size="sm" onClick={() => evaluate.mutate()}>
            Пересчитать
          </Button>
        </div>
      </div>

      {list.data?.comments_note ? (
        <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-[13px] text-muted-foreground">
          {list.data.comments_note}
        </p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(220px,0.85fr)_minmax(0,1.4fr)_minmax(240px,1fr)]">
        <aside className="panel overflow-hidden">
          <div className="border-b border-border px-3 py-2.5">
            <h2 className="section-title">Правила</h2>
          </div>
          <ul className="max-h-[70vh] overflow-y-auto">
            {items.length === 0 ? (
              <li className="px-3 py-4 text-[13px] text-muted-foreground">Правил нет</li>
            ) : (
              items.map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => loadRule(r)}
                    className={cn(
                      "interactive-row flex w-full flex-col gap-0.5 border-b border-border px-3 py-2.5 text-left last:border-0",
                      editId === r.id && "bg-accent",
                    )}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-[13px] font-medium">{r.rule_name || "—"}</span>
                      {r.enabled ? (
                        <Badge variant="success" className="shrink-0 text-[10px]">
                          {getBoolActiveLabel(true)}
                        </Badge>
                      ) : (
                        <Badge className="shrink-0 text-[10px]">{getBoolActiveLabel(false)}</Badge>
                      )}
                    </span>
                    <span className="truncate text-[11px] text-muted-foreground">
                      {getSeverityLabel(r.severity)}
                    </span>
                  </button>
                </li>
              ))
            )}
          </ul>
        </aside>

        <section className="panel panel-pad space-y-3">
          <h2 className="section-title">{editId ? `Редактирование #${editId}` : "Новое правило"}</h2>

          <div>
            <Label className="text-[12px]">Название</Label>
            <Input
              className="mt-1 h-8"
              value={form.rule_name ?? ""}
              onChange={(e) => setForm((f) => ({ ...f, rule_name: e.target.value }))}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-[12px]">Воронка</Label>
              <Input
                className="mt-1 h-8"
                type="number"
                value={form.pipeline_bitrix_id ?? ""}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    pipeline_bitrix_id: e.target.value ? Number(e.target.value) : null,
                  }))
                }
              />
            </div>
            <div>
              <Label className="text-[12px]">Этап</Label>
              <Input
                className="mt-1 h-8"
                type="number"
                value={form.stage_id ?? ""}
                onChange={(e) =>
                  setForm((f) => ({ ...f, stage_id: e.target.value ? Number(e.target.value) : null }))
                }
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-[12px]">Уровень</Label>
              <select
                className="mt-1 flex h-8 w-full rounded-md border border-input bg-background px-2 text-[13px]"
                value={form.severity ?? "medium"}
                onChange={(e) => setForm((f) => ({ ...f, severity: e.target.value }))}
              >
                <option value="low">{getSeverityLabel("low")}</option>
                <option value="medium">{getSeverityLabel("medium")}</option>
                <option value="high">{getSeverityLabel("high")}</option>
                <option value="critical">{getSeverityLabel("critical")}</option>
              </select>
            </div>
            <label className="flex items-end gap-2 pb-1 text-[13px]">
              <input
                type="checkbox"
                checked={Boolean(form.enabled)}
                onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
              />
              Включено
            </label>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-[12px]">Макс. простой, мин</Label>
              <p className="mt-0.5 text-[10px] text-muted-foreground">Без активности по сделке</p>
              <Input
                className="mt-1 h-8"
                type="number"
                value={form.max_idle_minutes ?? ""}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    max_idle_minutes: e.target.value ? Number(e.target.value) : null,
                  }))
                }
              />
            </div>
            <div>
              <Label className="text-[12px]">Макс. на этапе, мин</Label>
              <Input
                className="mt-1 h-8"
                type="number"
                value={form.max_stage_duration_minutes ?? ""}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    max_stage_duration_minutes: e.target.value ? Number(e.target.value) : null,
                  }))
                }
              />
            </div>
          </div>
          <div>
            <Label className="text-[12px]">Макс. до следующего дела, мин</Label>
            <Input
              className="mt-1 h-8"
              type="number"
              value={form.max_next_activity_minutes ?? ""}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  max_next_activity_minutes: e.target.value ? Number(e.target.value) : null,
                }))
              }
            />
          </div>
          <div className="flex flex-wrap gap-4 text-[13px]">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={form.future_activity_required === true}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    future_activity_required: e.target.checked ? true : null,
                  }))
                }
              />
              Требуется следующее дело
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={form.overdue_activity_allowed === false}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    overdue_activity_allowed: e.target.checked ? false : null,
                  }))
                }
              />
              Просроченные дела запрещены
            </label>
          </div>
          <div>
            <div className="mb-1 flex items-center justify-between">
              <Label className="text-[12px]">Обязательные поля</Label>
              <Button type="button" variant="outline" size="sm" className="h-7 text-[12px]" onClick={() => syncFields.mutate()}>
                Обновить поля
              </Button>
            </div>
            <select
              multiple
              className="h-28 w-full rounded-md border border-input bg-background px-2 text-[13px]"
              value={form.required_fields ?? []}
              onChange={(e) => {
                const opts = Array.from(e.target.selectedOptions).map((o) => o.value);
                setForm((f) => ({ ...f, required_fields: opts }));
              }}
            >
              {(fields.data?.items ?? []).map((f) => (
                <option key={f.field_name} value={f.field_name}>
                  {f.title || f.field_name}
                </option>
              ))}
            </select>
          </div>

          {error ? <p className="text-[13px] text-destructive">{error}</p> : null}

          <div className="flex flex-wrap gap-2 border-t border-border pt-3">
            <Button type="button" variant="outline" size="sm" onClick={() => previewMut.mutate()} disabled={previewMut.isPending}>
              Предпросмотр
            </Button>
            <Button type="button" size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
              {editId ? "Сохранить" : "Создать"}
            </Button>
            {editId ? (
              <Button type="button" size="sm" variant="ghost" onClick={() => editId && del.mutate(editId)}>
                Удалить
              </Button>
            ) : null}
          </div>
        </section>

        <aside className="panel panel-pad">
          <h2 className="section-title mb-3">Влияние правила</h2>
          {!preview ? (
            <p className="text-[13px] text-muted-foreground">
              Запустите предпросмотр, чтобы оценить влияние правила до включения.
            </p>
          ) : (
            <div className="space-y-3 text-[13px]">
              <p className="text-muted-foreground whitespace-pre-wrap">{human || preview.human_description}</p>
              <div className="border-t border-border pt-3">
                <p className="meta">Если включить сейчас</p>
                <p className="mt-1 text-[1.25rem] font-semibold tabular-nums">
                  {formatNumber(preview.deals_affected)} сделок
                </p>
                <p className="text-muted-foreground">{formatMoney(preview.amount_affected)}</p>
              </div>
              {preview.note ? <p className="meta">{preview.note}</p> : null}
              {preview.by_manager?.length ? (
                <ul className="space-y-1.5 border-t border-border pt-3">
                  {preview.by_manager.slice(0, 10).map((m) => (
                    <li key={String(m.manager_id)} className="flex justify-between gap-2">
                      <span className="truncate">{m.manager_name}</span>
                      <span className="shrink-0 tabular-nums text-muted-foreground">
                        {m.deals_count} · {formatMoney(m.amount)}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

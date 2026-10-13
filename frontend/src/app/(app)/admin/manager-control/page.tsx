"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { ErrorState, PageLoading } from "@/components/common/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import {
  SCHEDULE_FIELD_META,
  VIOLATION_TYPES,
  getBoolActiveLabel,
  getCalendarKindLabel,
  getSeverityLabel,
  getViolationLabel,
} from "@/lib/ui-labels";
import type { McCalendarOverride, McControlPolicy, McScheduleAssignment, McWorkSchedule } from "@/types/api";
import { cn } from "@/lib/utils";

type Tab = "schedules" | "assignments" | "calendar" | "policy" | "preview";

const emptySchedule: McWorkSchedule = {
  name: "",
  timezone: "Europe/Moscow",
  weekdays: [1, 2, 3, 4, 5],
  start_time: "09:00",
  end_time: "18:00",
  required_minutes: 480,
  late_grace_minutes: 10,
  early_finish_grace_minutes: 10,
  max_break_minutes: 60,
  not_started_threshold_minutes: 30,
  not_closed_grace_minutes: 15,
  enabled: true,
  is_default: false,
};

const WEEKDAY_LABELS: Record<number, string> = {
  1: "Пн",
  2: "Вт",
  3: "Ср",
  4: "Чт",
  5: "Пт",
  6: "Сб",
  7: "Вс",
};

const SCHEDULE_NUMBER_FIELDS = [
  "required_minutes",
  "late_grace_minutes",
  "early_finish_grace_minutes",
  "max_break_minutes",
  "not_started_threshold_minutes",
  "not_closed_grace_minutes",
] as const;

export default function ManagerControlAdminPage() {
  const [tab, setTab] = useState<Tab>("schedules");
  const qc = useQueryClient();

  const schedules = useQuery({ queryKey: ["mc-admin", "schedules"], queryFn: () => api.mcAdminSchedules() });
  const assignments = useQuery({
    queryKey: ["mc-admin", "assignments"],
    queryFn: () => api.mcAdminAssignments(),
  });
  const calendar = useQuery({ queryKey: ["mc-admin", "calendar"], queryFn: () => api.mcAdminCalendar() });
  const policy = useQuery({ queryKey: ["mc-admin", "policy"], queryFn: () => api.mcAdminPolicy() });
  const managers = useQuery({ queryKey: ["manager-control"], queryFn: () => api.managerControl() });

  const [scheduleForm, setScheduleForm] = useState<McWorkSchedule>(emptySchedule);
  const [scheduleEditId, setScheduleEditId] = useState<number | null>(null);
  const [assignForm, setAssignForm] = useState<{
    schedule_id: number;
    manager_id: string;
    department_key: string;
    note: string;
  }>({ schedule_id: 0, manager_id: "", department_key: "", note: "" });
  const [calForm, setCalForm] = useState({
    day_date: "",
    kind: "holiday",
    manager_id: "",
    label: "",
    note: "",
  });
  const [policyForm, setPolicyForm] = useState<McControlPolicy>({});
  const [previewParams, setPreviewParams] = useState({ schedule_id: "", manager_id: "", days: "7" });
  const [previewResult, setPreviewResult] = useState<Awaited<ReturnType<typeof api.mcAdminPreview>> | null>(null);
  const [error, setError] = useState<string | null>(null);

  const scheduleItems = schedules.data?.items ?? [];
  const managerItems = managers.data?.items ?? [];

  const saveSchedule = useMutation({
    mutationFn: async () => {
      if (scheduleEditId) return api.mcAdminUpdateSchedule(scheduleEditId, scheduleForm);
      return api.mcAdminCreateSchedule(scheduleForm);
    },
    onSuccess: async () => {
      setScheduleForm(emptySchedule);
      setScheduleEditId(null);
      await qc.invalidateQueries({ queryKey: ["mc-admin", "schedules"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const deleteSchedule = useMutation({
    mutationFn: (id: number) => api.mcAdminDeleteSchedule(id),
    onSuccess: async () => qc.invalidateQueries({ queryKey: ["mc-admin", "schedules"] }),
  });

  const saveAssignment = useMutation({
    mutationFn: () =>
      api.mcAdminCreateAssignment({
        schedule_id: assignForm.schedule_id,
        manager_id: assignForm.manager_id ? Number(assignForm.manager_id) : null,
        department_key: assignForm.department_key || null,
        note: assignForm.note || null,
      }),
    onSuccess: async () => {
      setAssignForm({ schedule_id: 0, manager_id: "", department_key: "", note: "" });
      await qc.invalidateQueries({ queryKey: ["mc-admin", "assignments"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const deleteAssignment = useMutation({
    mutationFn: (id: number) => api.mcAdminDeleteAssignment(id),
    onSuccess: async () => qc.invalidateQueries({ queryKey: ["mc-admin", "assignments"] }),
  });

  const saveCalendar = useMutation({
    mutationFn: () =>
      api.mcAdminUpsertCalendar({
        day_date: calForm.day_date,
        kind: calForm.kind,
        manager_id: calForm.manager_id ? Number(calForm.manager_id) : null,
        label: calForm.label || null,
        note: calForm.note || null,
      }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["mc-admin", "calendar"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const deleteCalendar = useMutation({
    mutationFn: (id: number) => api.mcAdminDeleteCalendar(id),
    onSuccess: async () => qc.invalidateQueries({ queryKey: ["mc-admin", "calendar"] }),
  });

  const savePolicy = useMutation({
    mutationFn: () => api.mcAdminPatchPolicy(policyForm),
    onSuccess: async (data) => {
      setPolicyForm(data);
      await qc.invalidateQueries({ queryKey: ["mc-admin", "policy"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const runPreview = useMutation({
    mutationFn: () =>
      api.mcAdminPreview({
        schedule_id: Number(previewParams.schedule_id),
        manager_id: Number(previewParams.manager_id),
        days: Number(previewParams.days) || 7,
      }),
    onSuccess: (data) => setPreviewResult(data),
    onError: (e: Error) => setError(e.message),
  });

  const policyLoaded = useMemo(() => {
    if (policy.data && !policyForm.enforcement_start_date && policyForm.severity_by_type === undefined) {
      return policy.data;
    }
    return policyForm;
  }, [policy.data, policyForm]);

  if (schedules.isLoading && tab === "schedules") return <PageLoading rows={5} />;
  if (schedules.isError)
    return <ErrorState message="Не удалось загрузить админку." onRetry={() => void schedules.refetch()} />;

  function loadSchedule(s: McWorkSchedule) {
    setScheduleEditId(s.id ?? null);
    setScheduleForm({ ...emptySchedule, ...s, weekdays: s.weekdays ?? [1, 2, 3, 4, 5] });
    setError(null);
  }

  function toggleWeekday(d: number) {
    setScheduleForm((f) => {
      const set = new Set(f.weekdays ?? []);
      if (set.has(d)) set.delete(d);
      else set.add(d);
      return { ...f, weekdays: Array.from(set).sort((a, b) => a - b) };
    });
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: "schedules", label: "Графики" },
    { id: "assignments", label: "Назначения" },
    { id: "calendar", label: "Календарь" },
    { id: "policy", label: "Политика" },
    { id: "preview", label: "Предпросмотр" },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] text-muted-foreground">Графики, назначения и пороги нарушений рабочего дня</p>
        <Link href="/manager-control" className="text-[13px] text-primary hover:underline">
          ← Доска контроля
        </Link>
      </div>

      <div className="flex flex-wrap gap-1 border-b border-border pb-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => {
              setTab(t.id);
              setError(null);
              if (t.id === "policy" && policy.data) setPolicyForm(policy.data);
            }}
            className={cn(
              "rounded-md px-3 py-1.5 text-[13px]",
              tab === t.id ? "bg-accent font-medium" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error ? <p className="text-[13px] text-destructive">{error}</p> : null}

      {tab === "schedules" ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(220px,0.85fr)_minmax(0,1.4fr)]">
          <aside className="panel overflow-hidden">
            <div className="border-b border-border px-3 py-2.5">
              <h2 className="section-title">Графики ({scheduleItems.length})</h2>
            </div>
            <ul className="max-h-[70vh] overflow-y-auto">
              {scheduleItems.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => loadSchedule(s)}
                    className={cn(
                      "interactive-row flex w-full flex-col gap-0.5 border-b border-border px-3 py-2.5 text-left last:border-0",
                      scheduleEditId === s.id && "bg-accent",
                    )}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-[13px] font-medium">{s.name}</span>
                      {s.enabled ? (
                        <Badge variant="success" className="shrink-0 text-[10px]">
                          {getBoolActiveLabel(true)}
                        </Badge>
                      ) : (
                        <Badge className="shrink-0 text-[10px]">{getBoolActiveLabel(false)}</Badge>
                      )}
                    </span>
                    <span className="text-[11px] text-muted-foreground tabular-nums">
                      {s.start_time}–{s.end_time}
                      {s.is_default ? " · по умолчанию" : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </aside>
          <section className="panel panel-pad space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="section-title">{scheduleEditId ? `График #${scheduleEditId}` : "Новый график"}</h2>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setScheduleEditId(null);
                  setScheduleForm(emptySchedule);
                }}
              >
                Создать график
              </Button>
            </div>
            <ScheduleFields form={scheduleForm} setForm={setScheduleForm} toggleWeekday={toggleWeekday} />
            <div className="flex gap-2 border-t border-border pt-3">
              <Button type="button" size="sm" onClick={() => saveSchedule.mutate()} disabled={saveSchedule.isPending}>
                Сохранить
              </Button>
              {scheduleEditId ? (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => deleteSchedule.mutate(scheduleEditId)}
                >
                  Удалить
                </Button>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}

      {tab === "assignments" ? (
        <div className="space-y-4">
          <div className="panel panel-pad grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <Label className="text-[12px]">График</Label>
              <select
                className="mt-1 flex h-8 w-full rounded-md border border-input bg-background px-2 text-[13px]"
                value={assignForm.schedule_id || ""}
                onChange={(e) => setAssignForm((f) => ({ ...f, schedule_id: Number(e.target.value) }))}
              >
                <option value="">—</option>
                {scheduleItems.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label className="text-[12px]">ID менеджера</Label>
              <Input
                className="mt-1 h-8"
                value={assignForm.manager_id}
                onChange={(e) => setAssignForm((f) => ({ ...f, manager_id: e.target.value }))}
                placeholder="ID менеджера"
              />
            </div>
            <div>
              <Label className="text-[12px]">Ключ отдела</Label>
              <Input
                className="mt-1 h-8"
                value={assignForm.department_key}
                onChange={(e) => setAssignForm((f) => ({ ...f, department_key: e.target.value }))}
                placeholder="Опционально"
              />
            </div>
            <div className="flex items-end">
              <Button type="button" size="sm" onClick={() => saveAssignment.mutate()} disabled={!assignForm.schedule_id}>
                Назначить
              </Button>
            </div>
          </div>
          <AssignmentsTable
            items={assignments.data?.items ?? []}
            schedules={scheduleItems}
            onDelete={(id) => deleteAssignment.mutate(id)}
          />
        </div>
      ) : null}

      {tab === "calendar" ? (
        <div className="space-y-4">
          <div className="panel panel-pad grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <div>
              <Label className="text-[12px]">Дата</Label>
              <Input
                type="date"
                className="mt-1 h-8"
                value={calForm.day_date}
                onChange={(e) => setCalForm((f) => ({ ...f, day_date: e.target.value }))}
              />
            </div>
            <div>
              <Label className="text-[12px]">Тип дня</Label>
              <select
                className="mt-1 flex h-8 w-full rounded-md border border-input bg-background px-2 text-[13px]"
                value={calForm.kind}
                onChange={(e) => setCalForm((f) => ({ ...f, kind: e.target.value }))}
              >
                <option value="holiday">{getCalendarKindLabel("holiday")}</option>
                <option value="short_day">{getCalendarKindLabel("short_day")}</option>
                <option value="working_override">{getCalendarKindLabel("working_override")}</option>
              </select>
            </div>
            <div>
              <Label className="text-[12px]">ID менеджера (опц.)</Label>
              <Input
                className="mt-1 h-8"
                value={calForm.manager_id}
                onChange={(e) => setCalForm((f) => ({ ...f, manager_id: e.target.value }))}
              />
            </div>
            <div>
              <Label className="text-[12px]">Подпись</Label>
              <Input className="mt-1 h-8" value={calForm.label} onChange={(e) => setCalForm((f) => ({ ...f, label: e.target.value }))} />
            </div>
            <div className="flex items-end">
              <Button type="button" size="sm" onClick={() => saveCalendar.mutate()} disabled={!calForm.day_date}>
                Сохранить
              </Button>
            </div>
          </div>
          <CalendarTable items={calendar.data?.items ?? []} onDelete={(id) => deleteCalendar.mutate(id)} />
        </div>
      ) : null}

      {tab === "policy" ? (
        <section className="panel panel-pad max-w-xl space-y-3">
          <h2 className="section-title">Политика и пороги</h2>
          {policy.isLoading ? (
            <p className="text-[13px] text-muted-foreground">Загрузка…</p>
          ) : (
            <>
              <div>
                <Label className="text-[12px]">Дата начала контроля</Label>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  До этой даты нарушения показываются как предпросмотр, без жёсткого контроля
                </p>
                <Input
                  type="date"
                  className="mt-1 h-8"
                  value={(policyForm.enforcement_start_date ?? policyLoaded.enforcement_start_date) || ""}
                  onChange={(e) =>
                    setPolicyForm((f) => ({
                      ...f,
                      enforcement_start_date: e.target.value || null,
                      severity_by_type: f.severity_by_type ?? policy.data?.severity_by_type ?? {},
                    }))
                  }
                />
              </div>
              <div>
                <Label className="text-[12px]">Уровень по типу нарушения</Label>
                <div className="mt-2 space-y-2">
                  {VIOLATION_TYPES.map((t) => (
                    <div key={t} className="flex items-center gap-2 text-[13px]">
                      <span className="min-w-0 flex-1 leading-snug text-muted-foreground">{getViolationLabel(t)}</span>
                      <select
                        className="h-8 flex-1 rounded-md border border-input bg-background px-2 text-[13px]"
                        value={
                          (policyForm.severity_by_type ?? policy.data?.severity_by_type ?? {})[t] ?? "medium"
                        }
                        onChange={(e) =>
                          setPolicyForm((f) => ({
                            ...f,
                            enforcement_start_date:
                              f.enforcement_start_date ?? policy.data?.enforcement_start_date ?? null,
                            severity_by_type: {
                              ...(f.severity_by_type ?? policy.data?.severity_by_type ?? {}),
                              [t]: e.target.value,
                            },
                          }))
                        }
                      >
                        <option value="low">{getSeverityLabel("low")}</option>
                        <option value="medium">{getSeverityLabel("medium")}</option>
                        <option value="high">{getSeverityLabel("high")}</option>
                        <option value="critical">{getSeverityLabel("critical")}</option>
                      </select>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <Label className="text-[12px]">Заметка</Label>
                <Input
                  className="mt-1 h-8"
                  value={policyForm.note ?? policy.data?.note ?? ""}
                  onChange={(e) =>
                    setPolicyForm((f) => ({
                      ...f,
                      note: e.target.value,
                      severity_by_type: f.severity_by_type ?? policy.data?.severity_by_type,
                    }))
                  }
                />
              </div>
              <Button type="button" size="sm" onClick={() => savePolicy.mutate()}>
                Сохранить
              </Button>
            </>
          )}
        </section>
      ) : null}

      {tab === "preview" ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <section className="panel panel-pad space-y-3">
            <h2 className="section-title">Предпросмотр графика</h2>
            <div>
              <Label className="text-[12px]">График</Label>
              <select
                className="mt-1 flex h-8 w-full rounded-md border border-input bg-background px-2 text-[13px]"
                value={previewParams.schedule_id}
                onChange={(e) => setPreviewParams((p) => ({ ...p, schedule_id: e.target.value }))}
              >
                <option value="">—</option>
                {scheduleItems.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label className="text-[12px]">Менеджер</Label>
              <select
                className="mt-1 flex h-8 w-full rounded-md border border-input bg-background px-2 text-[13px]"
                value={previewParams.manager_id}
                onChange={(e) => setPreviewParams((p) => ({ ...p, manager_id: e.target.value }))}
              >
                <option value="">—</option>
                {managerItems.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label className="text-[12px]">Дней истории</Label>
              <Input
                className="mt-1 h-8 w-24"
                type="number"
                min={1}
                max={31}
                value={previewParams.days}
                onChange={(e) => setPreviewParams((p) => ({ ...p, days: e.target.value }))}
              />
            </div>
            <Button
              type="button"
              size="sm"
              onClick={() => runPreview.mutate()}
              disabled={!previewParams.schedule_id || !previewParams.manager_id || runPreview.isPending}
            >
              Запустить предпросмотр
            </Button>
          </section>
          <aside className="panel panel-pad">
            <h2 className="section-title mb-3">Результат</h2>
            {!previewResult ? (
              <p className="text-[13px] text-muted-foreground">Оценка «что если» по доступной истории Timeman.</p>
            ) : (
              <div className="space-y-2 text-[13px]">
                {previewResult.message ? <p className="text-muted-foreground">{previewResult.message}</p> : null}
                <p>
                  Дней с данными: <span className="tabular-nums font-medium">{previewResult.days_with_data}</span>
                </p>
                <ul className="space-y-1 tabular-nums">
                  <li>Опоздания: {formatNumber(previewResult.late_starts)}</li>
                  <li>Не закрыт: {formatNumber(previewResult.not_closed)}</li>
                  <li>Короткий день: {formatNumber(previewResult.short_days)}</li>
                  <li>Не начат: {formatNumber(previewResult.not_started)}</li>
                  <li className="border-t border-border pt-2 font-medium">
                    Всего: {formatNumber(previewResult.total_violations)}
                  </li>
                </ul>
              </div>
            )}
          </aside>
        </div>
      ) : null}
    </div>
  );
}

function ScheduleFields({
  form,
  setForm,
  toggleWeekday,
}: {
  form: McWorkSchedule;
  setForm: Dispatch<SetStateAction<McWorkSchedule>>;
  toggleWeekday: (d: number) => void;
}) {
  return (
    <>
      <div>
        <Label className="text-[12px]">Название</Label>
        <Input className="mt-1 h-8" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label className="text-[12px]">{SCHEDULE_FIELD_META.start_time.label}</Label>
          <Input className="mt-1 h-8" value={form.start_time} onChange={(e) => setForm((f) => ({ ...f, start_time: e.target.value }))} />
        </div>
        <div>
          <Label className="text-[12px]">{SCHEDULE_FIELD_META.end_time.label}</Label>
          <Input className="mt-1 h-8" value={form.end_time} onChange={(e) => setForm((f) => ({ ...f, end_time: e.target.value }))} />
        </div>
      </div>
      <div>
        <Label className="text-[12px]">Дни недели</Label>
        <div className="mt-1 flex flex-wrap gap-1">
          {[1, 2, 3, 4, 5, 6, 7].map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => toggleWeekday(d)}
              className={cn(
                "rounded border px-2 py-0.5 text-[12px]",
                (form.weekdays ?? []).includes(d) ? "border-primary bg-primary/10" : "border-border text-muted-foreground",
              )}
            >
              {WEEKDAY_LABELS[d]}
            </button>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {SCHEDULE_NUMBER_FIELDS.map((key) => {
          const meta = SCHEDULE_FIELD_META[key];
          return (
            <div key={key}>
              <Label className="text-[12px] leading-snug">{meta.label}</Label>
              {meta.helper ? <p className="mt-0.5 text-[10px] leading-snug text-muted-foreground">{meta.helper}</p> : null}
              <Input
                className="mt-1 h-8"
                type="number"
                value={form[key] ?? ""}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    [key]: e.target.value ? Number(e.target.value) : null,
                  }))
                }
              />
            </div>
          );
        })}
      </div>
      <div className="flex flex-wrap gap-4 text-[13px]">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={Boolean(form.enabled)} onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))} />
          {SCHEDULE_FIELD_META.enabled.label}
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={Boolean(form.is_default)}
            onChange={(e) => setForm((f) => ({ ...f, is_default: e.target.checked }))}
          />
          {SCHEDULE_FIELD_META.is_default.label}
        </label>
      </div>
    </>
  );
}

function AssignmentsTable({
  items,
  schedules,
  onDelete,
}: {
  items: McScheduleAssignment[];
  schedules: McWorkSchedule[];
  onDelete: (id: number) => void;
}) {
  const byId = useMemo(() => new Map(schedules.map((s) => [s.id, s.name])), [schedules]);
  return (
    <div className="panel overflow-x-auto">
      <Table className="data-table">
        <TableHeader>
          <TableRow>
            <TableHead className="pl-4">ID</TableHead>
            <TableHead>График</TableHead>
            <TableHead>ID менеджера</TableHead>
            <TableHead>Отдел</TableHead>
            <TableHead className="pr-4 text-right"></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((a) => (
            <TableRow key={a.id}>
              <TableCell className="pl-4 tabular-nums">{a.id}</TableCell>
              <TableCell>{byId.get(a.schedule_id) ?? a.schedule_id}</TableCell>
              <TableCell className="tabular-nums">{a.manager_id ?? "—"}</TableCell>
              <TableCell>{a.department_key ?? "—"}</TableCell>
              <TableCell className="pr-4 text-right">
                <Button type="button" variant="ghost" size="sm" className="h-7 text-[12px]" onClick={() => onDelete(a.id)}>
                  Удалить
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function CalendarTable({
  items,
  onDelete,
}: {
  items: McCalendarOverride[];
  onDelete: (id: number) => void;
}) {
  return (
    <div className="panel overflow-x-auto">
      <Table className="data-table">
        <TableHeader>
          <TableRow>
            <TableHead className="pl-4">Дата</TableHead>
            <TableHead>Тип дня</TableHead>
            <TableHead>Менеджер</TableHead>
            <TableHead>Подпись</TableHead>
            <TableHead className="pr-4 text-right"></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((c) => (
            <TableRow key={c.id}>
              <TableCell className="pl-4">{c.day_date}</TableCell>
              <TableCell>{getCalendarKindLabel(c.kind)}</TableCell>
              <TableCell className="tabular-nums">{c.manager_id ?? "все"}</TableCell>
              <TableCell>{c.label ?? "—"}</TableCell>
              <TableCell className="pr-4 text-right">
                <Button type="button" variant="ghost" size="sm" className="h-7 text-[12px]" onClick={() => onDelete(c.id)}>
                  Удалить
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

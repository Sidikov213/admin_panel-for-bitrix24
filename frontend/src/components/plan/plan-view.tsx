"use client";

import { Check, Pencil, X } from "lucide-react";
import { useState } from "react";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { PLAN_STATUS, PlanBar, PlanProgressCard } from "@/components/plan/plan-progress-card";
import { TargetForm } from "@/components/plan/target-form";
import { useAuth } from "@/components/providers/auth-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useTargetMutations, useTargetsProgress } from "@/hooks/queries";
import { formatDate, formatMoney, formatPercent } from "@/lib/format";
import type { TargetProgress } from "@/types/api";

export function PlanView() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const all = useTargetsProgress(false);

  if (all.isLoading) return <PageLoading rows={3} />;
  if (all.isError) return <ErrorState message="Не удалось загрузить цели." onRetry={() => void all.refetch()} />;

  const items = all.data?.items ?? [];
  const active = items.filter((p) => p.active);
  const department = active.filter((p) => p.manager_id === null);
  const managers = active
    .filter((p) => p.manager_id !== null)
    .sort((a, b) => a.forecast_percent - b.forecast_percent);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-serif text-3xl font-semibold">План / факт</h1>
        <p className="text-sm text-muted-foreground">
          Факт — сумма выигранных сделок за период цели. Прогноз — текущий темп продаж, продлённый до конца периода.
        </p>
      </div>

      {!active.length ? (
        <EmptyState
          title="Нет целей на сегодня"
          description={isAdmin ? "Добавьте план на месяц ниже." : "Администратор ещё не задал план."}
        />
      ) : (
        <>
          {department.length ? (
            <div className="grid max-w-3xl gap-4">
              {department.map((p) => (
                <PlanProgressCard key={p.target_id} p={p} />
              ))}
            </div>
          ) : null}
          {managers.length ? (
            <div>
              <h2 className="mb-3 font-serif text-xl font-semibold">Менеджеры</h2>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {managers.map((p) => (
                  <PlanProgressCard key={p.target_id} p={p} compact />
                ))}
              </div>
            </div>
          ) : null}
        </>
      )}

      {isAdmin ? <TargetForm /> : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Все цели</CardTitle>
        </CardHeader>
        <CardContent>
          {!items.length ? (
            <p className="text-sm text-muted-foreground">Целей пока нет.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Период</TableHead>
                  <TableHead>Для кого</TableHead>
                  <TableHead>План</TableHead>
                  <TableHead>Факт</TableHead>
                  <TableHead className="w-40">Выполнение</TableHead>
                  <TableHead>Статус</TableHead>
                  {isAdmin ? <TableHead /> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((p) => (
                  <TargetRow key={p.target_id} p={p} isAdmin={isAdmin} />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function TargetRow({ p, isAdmin }: { p: TargetProgress; isAdmin: boolean }) {
  const { update, remove } = useTargetMutations();
  const [editing, setEditing] = useState(false);
  const [amount, setAmount] = useState(String(p.plan));
  const value = amount.replace(/\s/g, "").replace(",", ".");
  const valid = /^\d+(\.\d{1,2})?$/.test(value) && Number(value) > 0;
  const s = PLAN_STATUS[p.status];

  return (
    <TableRow>
      <TableCell className="whitespace-nowrap">
        {formatDate(p.period_start)} — {formatDate(p.period_end)}
      </TableCell>
      <TableCell>{p.manager_id === null ? "Весь отдел" : (p.manager_name ?? `#${p.manager_id}`)}</TableCell>
      <TableCell className="whitespace-nowrap">
        {editing ? (
          <form
            className="flex items-center gap-1"
            onSubmit={(e) => {
              e.preventDefault();
              if (!valid) return;
              update.mutate({ id: p.target_id, body: { amount: value } }, { onSuccess: () => setEditing(false) });
            }}
          >
            <Input
              aria-label="Сумма плана"
              className="h-8 w-32"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              autoFocus
            />
            <Button type="submit" size="sm" variant="ghost" disabled={!valid || update.isPending} aria-label="Сохранить">
              <Check className="h-4 w-4" />
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)} aria-label="Отмена">
              <X className="h-4 w-4" />
            </Button>
          </form>
        ) : (
          formatMoney(p.plan, p.currency)
        )}
      </TableCell>
      <TableCell className="whitespace-nowrap">{formatMoney(p.fact, p.currency)}</TableCell>
      <TableCell>
        <div className="flex items-center gap-2">
          <PlanBar p={p} className="h-2" />
          <span className="w-16 text-right text-sm tabular-nums">{formatPercent(p.percent)}</span>
        </div>
      </TableCell>
      <TableCell>
        <Badge variant={s.variant}>{s.label}</Badge>
      </TableCell>
      {isAdmin ? (
        <TableCell className="whitespace-nowrap text-right">
          {!editing ? (
            <Button size="sm" variant="ghost" onClick={() => setEditing(true)} aria-label="Изменить сумму">
              <Pencil className="h-4 w-4" />
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="ghost"
            disabled={remove.isPending}
            aria-label="Удалить цель"
            onClick={() => {
              if (window.confirm("Удалить эту цель?")) remove.mutate(p.target_id);
            }}
          >
            <X className="h-4 w-4" />
          </Button>
        </TableCell>
      ) : null}
    </TableRow>
  );
}

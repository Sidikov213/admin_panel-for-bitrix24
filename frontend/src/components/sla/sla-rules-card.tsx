"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { selectClass } from "@/components/common/scope-filters";
import { useSlaRuleMutations, useSlaRules } from "@/hooks/queries";
import type { SlaRule, SlaUnit } from "@/types/api";

const WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];

export function SlaRulesCard({ editable }: { editable: boolean }) {
  const rules = useSlaRules();
  const data = rules.data;
  if (!data) return null;
  const cal = data.work_calendar;
  const days = cal.workdays.length === 5 && cal.workdays[0] === 0 ? "пн–пт" : cal.workdays.map((d) => WEEKDAYS[d]).join(", ");

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Сроки по стадиям</CardTitle>
        <CardDescription>
          Через сколько сделка считается зависшей на стадии. Рабочее время: {days} {cal.hours}
          {cal.holidays.length ? `, кроме ${cal.holidays.join(", ")}` : ""}. Стадии «реакции» участвуют в расчёте скорости
          реакции на новые заявки.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Воронка</TableHead>
              <TableHead>Стадия</TableHead>
              <TableHead>Срок</TableHead>
              <TableHead>Реакция</TableHead>
              {editable ? <TableHead /> : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.map((r) => (
              <RuleRow key={r.stage_bitrix_id} rule={r} units={data.units} editable={editable} />
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function RuleRow({ rule, units, editable }: { rule: SlaRule; units: Record<SlaUnit, string>; editable: boolean }) {
  const { save, reset } = useSlaRuleMutations();
  const [editing, setEditing] = useState(false);
  const [threshold, setThreshold] = useState(rule.threshold === null ? "" : String(rule.threshold));
  const [unit, setUnit] = useState<SlaUnit>(rule.unit);
  const [reaction, setReaction] = useState(rule.reaction_stage);
  const value = threshold.trim().replace(",", ".");
  const valid = value === "" || (/^\d+(\.\d{1,2})?$/.test(value) && Number(value) > 0 && Number(value) <= 1000);

  return (
    <TableRow>
      <TableCell className="text-muted-foreground">{rule.pipeline_name}</TableCell>
      <TableCell className="font-medium">{rule.stage_name}</TableCell>
      <TableCell>
        {editing ? (
          <div className="flex flex-wrap items-center gap-2">
            <Input
              aria-label="Срок"
              className="h-9 w-20"
              placeholder="нет"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
            />
            <select aria-label="Единица" className={`${selectClass} h-9 w-44`} value={unit} onChange={(e) => setUnit(e.target.value as SlaUnit)}>
              {(Object.keys(units) as SlaUnit[]).map((u) => (
                <option key={u} value={u}>
                  {units[u]}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <span className="whitespace-nowrap">
            {rule.label}
            {rule.source === "custom" ? (
              <Badge variant="secondary" className="ml-2">
                изменено
              </Badge>
            ) : null}
          </span>
        )}
      </TableCell>
      <TableCell>
        {editing ? (
          <input type="checkbox" aria-label="Стадия реакции" checked={reaction} onChange={(e) => setReaction(e.target.checked)} />
        ) : rule.reaction_stage ? (
          "да"
        ) : (
          "—"
        )}
      </TableCell>
      {editable ? (
        <TableCell className="whitespace-nowrap text-right">
          {editing ? (
            <>
              <Button
                size="sm"
                disabled={!valid || save.isPending}
                onClick={() =>
                  save.mutate(
                    {
                      stageId: rule.stage_bitrix_id,
                      body: { threshold: value === "" ? null : Number(value), unit, reaction_stage: reaction },
                    },
                    { onSuccess: () => setEditing(false) },
                  )
                }
              >
                Сохранить
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                Отмена
              </Button>
            </>
          ) : (
            <>
              <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
                Изменить
              </Button>
              {rule.source === "custom" ? (
                <Button size="sm" variant="ghost" disabled={reset.isPending} onClick={() => reset.mutate(rule.stage_bitrix_id)}>
                  По умолчанию
                </Button>
              ) : null}
            </>
          )}
          {!valid ? <p className="text-xs text-destructive">Число от 0 до 1000 или пусто</p> : null}
        </TableCell>
      ) : null}
    </TableRow>
  );
}

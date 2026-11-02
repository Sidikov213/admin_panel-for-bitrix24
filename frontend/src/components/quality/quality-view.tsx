"use client";

import Link from "next/link";
import { useState } from "react";
import { EmptyState, ErrorState, PageLoading } from "@/components/common/page-states";
import { BitrixLink, ScopeFilters, selectClass } from "@/components/common/scope-filters";
import { useAuth } from "@/components/providers/auth-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useQuality, useQualityRuleMutations, useQualityRules } from "@/hooks/queries";
import { formatDateTime, formatMoney, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { QualityRule, QualityRulesResponse } from "@/types/api";

export function QualityView() {
  const { user } = useAuth();
  const [categoryId, setCategoryId] = useState<number | undefined>();
  const [managerId, setManagerId] = useState<number | undefined>();
  const [check, setCheck] = useState<string | undefined>();
  const q = useQuality({ category_id: categoryId, manager_id: managerId, check });
  const d = q.data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-serif text-3xl font-semibold">Качество карточек</h1>
        <p className="text-sm text-muted-foreground">
          Проверка открытых сделок по регламенту: следующее дело, комментарий «Дата / Цель / Итог / Следующий шаг», название
          по шаблону, обязательные поля стадии.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <ScopeFilters idPrefix="quality" categoryId={categoryId} managerId={managerId} onCategory={setCategoryId} onManager={setManagerId} />
      </div>

      {q.isLoading && !d ? (
        <PageLoading rows={3} />
      ) : q.isError ? (
        <ErrorState message="Не удалось проверить карточки." onRetry={() => void q.refetch()} />
      ) : d ? (
        <>
          {d.notes.map((n) => (
            <p key={n} className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900">
              {n}
            </p>
          ))}
          <div className="grid gap-4 lg:grid-cols-3">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">С нарушениями</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="font-serif text-3xl font-semibold">{d.with_issues}</p>
                <p className="text-xs text-muted-foreground">
                  из {d.checked} проверенных · {formatPercent(d.share)}
                </p>
              </CardContent>
            </Card>
            <Card className="min-w-0 lg:col-span-2">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">Что не так — нажмите, чтобы отфильтровать</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                {d.by_check.length ? (
                  d.by_check.map((b) => (
                    <button
                      key={b.code}
                      type="button"
                      onClick={() => setCheck(check === b.code ? undefined : b.code)}
                      className={cn(
                        "rounded-full border px-3 py-1 text-left text-sm",
                        check === b.code ? "border-primary bg-primary text-primary-foreground" : "border-border hover:bg-muted",
                      )}
                    >
                      {b.label} · <strong>{b.count}</strong>
                    </button>
                  ))
                ) : (
                  <span className="text-sm text-muted-foreground">Нарушений нет 👍</span>
                )}
              </CardContent>
            </Card>
          </div>

          {!d.items.length ? (
            <EmptyState title="Карточки в порядке" />
          ) : (
            <Card>
              <CardContent className="pt-6">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Сделка</TableHead>
                      <TableHead>Что не так</TableHead>
                      <TableHead>Последний комментарий</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {d.items.map((i) => (
                      <TableRow key={i.deal_id}>
                        <TableCell className="align-top">
                          <Link href={`/deals/${i.deal_id}`} className="font-medium text-primary hover:underline">
                            №{i.bitrix_id} {i.title}
                          </Link>
                          <p className="text-xs text-muted-foreground">
                            {[i.manager, i.stage, i.opportunity ? formatMoney(i.opportunity) : null].filter(Boolean).join(" · ")}
                          </p>
                          <BitrixLink href={i.bitrix_url} />
                        </TableCell>
                        <TableCell className="align-top">
                          <ul className="space-y-1">
                            {i.issues.map((x) => (
                              <li key={x.code}>
                                <Badge variant="warning" className="whitespace-normal text-left">
                                  {x.label}
                                </Badge>
                              </li>
                            ))}
                          </ul>
                        </TableCell>
                        <TableCell className="max-w-sm align-top text-sm">
                          {i.last_comment ? (
                            <>
                              <p className="line-clamp-3 whitespace-pre-line">{i.last_comment.text}</p>
                              <p className="text-xs text-muted-foreground">{formatDateTime(i.last_comment.at)}</p>
                            </>
                          ) : (
                            <span className="text-muted-foreground">нет</span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}

          {d.by_manager.length && managerId === undefined ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">По менеджерам</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Менеджер</TableHead>
                      <TableHead>Проверено</TableHead>
                      <TableHead>С нарушениями</TableHead>
                      <TableHead>Доля</TableHead>
                      <TableHead>Всего нарушений</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {d.by_manager.map((m) => (
                      <TableRow key={m.manager_id}>
                        <TableCell>{m.name ?? `#${m.manager_id}`}</TableCell>
                        <TableCell>{m.checked}</TableCell>
                        <TableCell>{m.with_issues}</TableCell>
                        <TableCell>{formatPercent(m.share)}</TableCell>
                        <TableCell>{m.issues}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          ) : null}
        </>
      ) : null}

      <QualityRulesCard editable={user?.role === "admin"} />
    </div>
  );
}

function QualityRulesCard({ editable }: { editable: boolean }) {
  const rules = useQualityRules();
  if (!rules.data) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Проверки по стадиям</CardTitle>
        <CardDescription>
          По умолчанию — по регламенту воронки «Сваи». Поля «Прибыль по расчёту», «Дата монтажа» и «Причина закрытия»
          подбираются автоматически по названию поля в Bitrix.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {rules.data.items.map((r) => (
          <RuleRow key={r.stage_bitrix_id} rule={r} meta={rules.data} editable={editable} />
        ))}
      </CardContent>
    </Card>
  );
}

function RuleRow({ rule, meta, editable }: { rule: QualityRule; meta: QualityRulesResponse; editable: boolean }) {
  const { save, reset } = useQualityRuleMutations();
  const [editing, setEditing] = useState(false);
  const [checks, setChecks] = useState<string[]>(rule.checks);
  const [addField, setAddField] = useState("");
  const base = Object.keys(meta.checks);
  const fieldLabel = (code: string) => meta.fields.find((f) => f.code === code)?.label ?? code;
  const toggle = (c: string) => setChecks((cur) => (cur.includes(c) ? cur.filter((x) => x !== c) : [...cur, c]));

  return (
    <div className="rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium">
            {rule.stage_name}
            {rule.source === "custom" ? (
              <Badge variant="secondary" className="ml-2">
                изменено
              </Badge>
            ) : null}
          </p>
          <p className="text-xs text-muted-foreground">{rule.pipeline_name}</p>
        </div>
        {editable && !editing ? (
          <div className="flex gap-1">
            <Button size="sm" variant="ghost" onClick={() => { setChecks(rule.checks); setEditing(true); }}>
              Изменить
            </Button>
            {rule.source === "custom" ? (
              <Button size="sm" variant="ghost" disabled={reset.isPending} onClick={() => reset.mutate(rule.stage_bitrix_id)}>
                По умолчанию
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>
      {!editing ? (
        <p className="mt-1 text-sm text-muted-foreground">
          {rule.checks.length ? Object.values(rule.check_labels).join(" · ") : "не проверяется"}
        </p>
      ) : (
        <div className="mt-2 space-y-2 text-sm">
          {base.map((c) => (
            <label key={c} className="flex items-center gap-2">
              <input type="checkbox" checked={checks.includes(c)} onChange={() => toggle(c)} />
              {meta.checks[c]}
            </label>
          ))}
          <div className="flex flex-wrap gap-2">
            {checks
              .filter((c) => c.startsWith("field:"))
              .map((c) => (
                <button key={c} type="button" className="rounded-full border border-border px-2 py-0.5 hover:bg-muted" onClick={() => toggle(c)}>
                  {fieldLabel(c.slice(6))} ✕
                </button>
              ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select aria-label="Обязательное поле" className={`${selectClass} h-9 w-64`} value={addField} onChange={(e) => setAddField(e.target.value)}>
              <option value="">Добавить обязательное поле…</option>
              {meta.fields
                .filter((f) => !checks.includes(`field:${f.code}`))
                .map((f) => (
                  <option key={f.code} value={f.code}>
                    {f.label}
                  </option>
                ))}
            </select>
            <Button
              size="sm"
              variant="outline"
              disabled={!addField}
              onClick={() => {
                toggle(`field:${addField}`);
                setAddField("");
              }}
            >
              Добавить
            </Button>
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={save.isPending}
              onClick={() => save.mutate({ stageId: rule.stage_bitrix_id, checks }, { onSuccess: () => setEditing(false) })}
            >
              Сохранить
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Отмена
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

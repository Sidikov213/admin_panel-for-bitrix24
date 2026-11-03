"""Card quality checks from the «Сваи» regulations (регламент воронки, ТЗ §15 «По карточкам»).

Rule-based, no AI: next activity is always set, the comment follows the form
«Дата / Цель / Итог / Следующий шаг», the title follows «Имя, тип свай, кол-во, место»,
required fields are filled. Which checks apply on which stage has defaults by stage name;
an admin overrides them per stage.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analytics.kpi import _as_utc
from app.core.timezone import utc_now
from app.integrations.bitrix.links import deal_url
from app.models.crm import CardQualityRule, CrmDeal, CrmPipeline, CrmStage, DealComment, DealStageHistory
from app.repositories.sync import SyncRepository
from app.services.sync_service import COMMENTS_STATE, DEAL_FIELDS_STATE

CHECK_LABELS = {
    "next_activity": "Не назначено следующее дело",
    "comment_form": "Последний комментарий не по форме «Дата / Цель / Итог / Следующий шаг»",
    "comment_after_stage": "Нет комментария после перехода на текущую стадию",
    "title_template": "Название не по шаблону «Имя, тип свай, кол-во, место»",
}
# Standard deal fields that are always present in crm.deal.list
STANDARD_FIELD_LABELS = {"OPPORTUNITY": "Сумма", "TYPE_ID": "Тип сделки", "COMMENTS": "Комментарий (слева)"}
COMMENT_PARTS = ("дата", "цель", "итог", "следующий шаг")
# «Алексей С30.20 26шт Чехов»: a name, a pile type like С30.20, a quantity in «шт», a place
TITLE_RE = re.compile(
    r"^\s*[^\d\s,]\S*[\s,]+.*?[СCсc]\s?\d{2}[.,]\d{2}.*?\d+\s*шт\.?[\s,]+\S",
    re.IGNORECASE,
)
_WORK_STAGES = (
    "квалиф", "контакт установлен", "кп с расч", "пробное бурение", "подготовка к монтажу",
    "поставлен в график", "монтаж", "итоговую оплату",
)

# Field checks resolved from the Bitrix field dictionary by label (UF codes differ per portal)
FIELD_HINTS = {
    "profit": ("прибыль",),
    "mount_date": ("дата монтажа", "ориентировочная дата"),
    "close_reason": ("причина закрытия", "причина отказа", "причина провала"),
}


def default_checks(stage_name: str, field_codes: dict[str, str]) -> list[str]:
    """Checks the regulations require on a stage. field_codes: hint → resolved UF code."""
    name = stage_name.lower()
    base = ["next_activity", "comment_form", "comment_after_stage"]
    if any(k in name for k in ("не обработан", "новая заявка")):
        # Card is only read and moved on; deadlines are watched by the stage SLA instead
        return []
    if "предзакрытие" in name:
        return ["comment_form", *([f"field:{field_codes['close_reason']}"] if "close_reason" in field_codes else [])]
    if "взят в работу" in name or "недозвон" in name:
        return [*base, "field:TYPE_ID"]
    if any(k in name for k in _WORK_STAGES):
        extra = [f"field:{field_codes[h]}" for h in ("profit", "mount_date") if h in field_codes]
        return [*base, "title_template", "field:TYPE_ID", "field:OPPORTUNITY", *extra]
    # Other open stages (e.g. «Отложенный спрос»): next activity is always required (ТЗ §15)
    return ["next_activity"]


def resolve_field_hints(fields: dict[str, dict[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for hint, keywords in FIELD_HINTS.items():
        for code, meta in fields.items():
            label = str(meta.get("label", "")).lower()
            if code.startswith("UF_") and any(k in label for k in keywords):
                out[hint] = code
                break
    return out


def field_label(code: str, fields: dict[str, dict[str, str]]) -> str:
    return STANDARD_FIELD_LABELS.get(code) or fields.get(code, {}).get("label") or code


def check_label(check: str, fields: dict[str, dict[str, str]]) -> str:
    if check.startswith("field:"):
        return f"Не заполнено поле «{field_label(check[6:], fields)}»"
    return CHECK_LABELS.get(check, check)


def is_filled(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        v = value.strip()
        return bool(v) and v not in ("0", "0.00", "N")
    if isinstance(value, (list, dict)):
        return any(is_filled(x) for x in (value.values() if isinstance(value, dict) else value))
    if isinstance(value, (int, float, Decimal)):
        return value != 0
    return True


def comment_has_form(text: str) -> bool:
    low = text.lower()
    return all(re.search(rf"{re.escape(part)}\s*[:\-–—]", low) for part in COMMENT_PARTS)


async def load_quality_rules(session: AsyncSession) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, str]]]:
    """{stage_bitrix_id: {stage, pipeline, checks, source}}, plus the deal field dictionary."""
    fields = await SyncRepository(session).get_state(DEAL_FIELDS_STATE) or {}
    hints = resolve_field_hints(fields)
    stages = (
        await session.execute(
            select(CrmStage, CrmPipeline)
            .join(CrmPipeline, CrmPipeline.id == CrmStage.pipeline_id)
            .where(CrmStage.semantics.is_(None) | CrmStage.semantics.notin_(("success", "failure")))
            .order_by(CrmPipeline.sort, CrmPipeline.id, CrmStage.sort, CrmStage.id)
        )
    ).all()
    custom = {r.stage_bitrix_id: r for r in (await session.execute(select(CardQualityRule))).scalars()}
    rules: dict[str, dict[str, Any]] = {}
    for stage, pipe in stages:
        override = custom.get(stage.bitrix_id)
        checks = list(override.checks) if override else default_checks(stage.name, hints)
        rules[stage.bitrix_id] = {
            "stage_bitrix_id": stage.bitrix_id,
            "stage_name": stage.name,
            "pipeline_name": pipe.name,
            "category_id": pipe.bitrix_id,
            "checks": checks,
            "check_labels": {c: check_label(c, fields) for c in checks},
            "source": "custom" if override else "default",
        }
    return rules, fields


async def card_quality(
    session: AsyncSession,
    *,
    category_id: int | None = None,
    manager_id: int | None = None,
    check: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or utc_now()
    rules, fields = await load_quality_rules(session)
    comments_synced = await SyncRepository(session).get_state(COMMENTS_STATE) is not None

    filters = [CrmDeal.closed.is_(False), CrmDeal.missing_from_bitrix.is_(False)]
    if category_id is not None:
        filters.append(CrmDeal.category_id == category_id)
    if manager_id is not None:
        filters.append(CrmDeal.assigned_by_id == manager_id)
    deals = (
        await session.execute(
            select(CrmDeal).where(*filters).options(selectinload(CrmDeal.stage), selectinload(CrmDeal.assigned_manager))
        )
    ).scalars().all()
    bids = [d.bitrix_id for d in deals]

    last_comment: dict[int, DealComment] = {}
    entered: dict[tuple[int, str], datetime] = {}
    for i in range(0, len(bids), 1000):
        chunk = bids[i : i + 1000]
        for c in (await session.execute(select(DealComment).where(DealComment.deal_bitrix_id.in_(chunk)))).scalars():
            if c.deal_bitrix_id not in last_comment or _as_utc(c.created) > _as_utc(last_comment[c.deal_bitrix_id].created):
                last_comment[c.deal_bitrix_id] = c
        for h in (
            await session.execute(
                select(DealStageHistory)
                .where(DealStageHistory.deal_bitrix_id.in_(chunk))
                .order_by(DealStageHistory.created_time)
            )
        ).scalars():
            entered[(h.deal_bitrix_id, h.stage_bitrix_id)] = _as_utc(h.created_time)

    items: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    by_manager: dict[int, dict[str, Any]] = {}
    checked = no_fields = 0
    for d in deals:
        rule = rules.get(d.stage.bitrix_id) if d.stage else None
        if rule is None or not rule["checks"]:
            continue
        checked += 1
        issues: list[str] = []
        comment = last_comment.get(d.bitrix_id)
        for c in rule["checks"]:
            if c == "next_activity":
                failed = not d.has_future_activity
            elif c in ("comment_form", "comment_after_stage"):
                if not comments_synced:
                    continue  # comments never synced: unknown, not a violation
                if c == "comment_form":
                    failed = comment is None or not comment_has_form(comment.text)
                else:
                    since = entered.get((d.bitrix_id, d.stage.bitrix_id)) or _as_utc(d.stage_changed_observed_at)
                    failed = comment is None or (since is not None and _as_utc(comment.created) < since)
            elif c == "title_template":
                failed = not TITLE_RE.search(d.title or "")
            elif c == "field:OPPORTUNITY":
                # Synced column: available even before the raw payload with UF_* arrives
                failed = not is_filled(d.opportunity)
            elif c.startswith("field:"):
                if d.raw is None:
                    no_fields += 1
                    continue
                failed = not is_filled(d.raw.get(c[6:]))
            else:
                continue
            if failed:
                issues.append(c)
                counts[c] = counts.get(c, 0) + 1

        if d.assigned_by_id:
            m = by_manager.setdefault(
                d.assigned_by_id,
                {"manager_id": d.assigned_by_id,
                 "name": f"{d.assigned_manager.last_name} {d.assigned_manager.name}".strip() if d.assigned_manager else None,
                 "checked": 0, "with_issues": 0, "issues": 0},
            )
            m["checked"] += 1
            m["with_issues"] += bool(issues)
            m["issues"] += len(issues)
        if not issues or (check and check not in issues):
            continue
        items.append(
            {
                "deal_id": d.id,
                "bitrix_id": d.bitrix_id,
                "title": d.title,
                "manager": by_manager.get(d.assigned_by_id, {}).get("name") if d.assigned_by_id else None,
                "stage": d.stage.name,
                "pipeline": rule["pipeline_name"],
                "opportunity": float(d.opportunity) if d.opportunity is not None else None,
                "issues": [{"code": c, "label": check_label(c, fields)} for c in issues],
                "last_comment": (
                    {"at": _as_utc(comment.created).isoformat(), "text": comment.text[:300]} if comment else None
                ),
                "bitrix_url": deal_url(d.bitrix_id),
            }
        )
    items.sort(key=lambda i: (-len(i["issues"]), -(i["opportunity"] or 0)))
    for m in by_manager.values():
        m["share"] = round(m["with_issues"] / m["checked"] * 100, 1) if m["checked"] else None
    with_issues = sum(m["with_issues"] for m in by_manager.values())
    notes = []
    if not comments_synced:
        notes.append("Комментарии из Bitrix ещё не загружены — проверки комментариев пропущены.")
    if no_fields:
        notes.append("У части сделок ещё нет полей из Bitrix (появятся после ближайшей полной синхронизации) — проверки полей для них пропущены.")
    if not fields:
        notes.append("Справочник полей Bitrix не загружен — поля «Прибыль», «Дата монтажа», «Причина закрытия» не подобраны автоматически.")
    return {
        "checked": checked,
        "with_issues": with_issues,
        "share": round(with_issues / checked * 100, 1) if checked else None,
        "by_check": sorted(
            ({"code": c, "label": check_label(c, fields), "count": n} for c, n in counts.items()),
            key=lambda x: -x["count"],
        ),
        "by_manager": sorted(by_manager.values(), key=lambda m: -(m["share"] or 0)),
        "items": items,
        "total": len(items),
        "notes": notes,
        "computed_at": now.isoformat(),
    }


def validate_checks(checks: list[str], fields: dict[str, dict[str, str]]) -> None:
    for c in checks:
        if c in CHECK_LABELS:
            continue
        if c.startswith("field:") and (c[6:] in STANDARD_FIELD_LABELS or c[6:] in fields):
            continue
        raise ValueError(f"Неизвестная проверка: {c}")

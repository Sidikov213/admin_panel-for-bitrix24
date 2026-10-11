"""Objective attention signals — facts only until sales rules are configured."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.timezone import utc_now
from app.models.crm import CrmActivity, CrmDeal, CrmStage


def format_duration(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    total_m = int(seconds // 60)
    days, rem_m = divmod(total_m, 60 * 24)
    hours, minutes = divmod(rem_m, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}д")
    if hours or days:
        parts.append(f"{hours}ч")
    parts.append(f"{minutes}м")
    return " ".join(parts)


def _as_utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


async def money_requiring_attention(
    session: AsyncSession,
    *,
    pipeline_id: int | None = None,
    manager_id: int | None = None,
) -> dict[str, Any]:
    """
    Sum of active deal opportunity where:
      - no future activity, OR
      - has at least one open overdue activity
    Each deal counted once.
    """
    now = utc_now()
    overdue_owners = (
        select(CrmActivity.owner_id)
        .where(
            CrmActivity.completed.is_(False),
            CrmActivity.deadline.isnot(None),
            CrmActivity.deadline < now,
            CrmActivity.owner_id.isnot(None),
        )
        .distinct()
        .scalar_subquery()
    )
    filters = [
        CrmDeal.closed.is_(False),
        CrmDeal.missing_from_bitrix.is_(False),
        or_(CrmDeal.has_future_activity.is_(False), CrmDeal.bitrix_id.in_(overdue_owners)),
    ]
    if pipeline_id is not None:
        filters.append(CrmDeal.category_id == pipeline_id)
    if manager_id is not None:
        filters.append(CrmDeal.assigned_by_id == manager_id)

    row = (
        await session.execute(
            select(
                func.count(CrmDeal.id),
                func.coalesce(func.sum(CrmDeal.opportunity), 0),
            ).where(*filters)
        )
    ).one()
    count = int(row[0] or 0)
    amount = float(row[1] or 0)
    return {
        "label": "Сумма сделок, требующих внимания",
        "deals_count": count,
        "amount": amount,
        "definition": (
            "Активные сделки без будущего дела или с просроченным незавершённым делом. "
            "Сделка учитывается один раз."
        ),
    }


async def no_future_summary(
    session: AsyncSession,
    *,
    pipeline_id: int | None = None,
    manager_id: int | None = None,
) -> dict[str, Any]:
    filters = [
        CrmDeal.closed.is_(False),
        CrmDeal.missing_from_bitrix.is_(False),
        CrmDeal.has_future_activity.is_(False),
    ]
    if pipeline_id is not None:
        filters.append(CrmDeal.category_id == pipeline_id)
    if manager_id is not None:
        filters.append(CrmDeal.assigned_by_id == manager_id)
    row = (
        await session.execute(
            select(func.count(CrmDeal.id), func.coalesce(func.sum(CrmDeal.opportunity), 0)).where(*filters)
        )
    ).one()
    return {
        "deals_count": int(row[0] or 0),
        "amount": float(row[1] or 0),
        "label": "без следующего действия",
    }


async def build_attention_items(
    session: AsyncSession,
    *,
    pipeline_id: int | None = None,
    manager_id: int | None = None,
    limit: int = 80,
) -> dict[str, Any]:
    """Categorised attention list from objective facts (no invented SLA)."""
    now = utc_now()
    money = await money_requiring_attention(session, pipeline_id=pipeline_id, manager_id=manager_id)

    overdue_acts = (
        await session.execute(
            select(CrmActivity)
            .where(
                CrmActivity.completed.is_(False),
                CrmActivity.deadline.isnot(None),
                CrmActivity.deadline < now,
            )
            .order_by(CrmActivity.deadline.asc())
        )
    ).scalars().all()
    overdue_by_owner: dict[int, CrmActivity] = {}
    for a in overdue_acts:
        if a.owner_id is None:
            continue
        # keep earliest deadline per deal
        prev = overdue_by_owner.get(a.owner_id)
        if prev is None or (a.deadline and prev.deadline and a.deadline < prev.deadline):
            overdue_by_owner[a.owner_id] = a

    filters = [CrmDeal.closed.is_(False), CrmDeal.missing_from_bitrix.is_(False)]
    if pipeline_id is not None:
        filters.append(CrmDeal.category_id == pipeline_id)
    if manager_id is not None:
        filters.append(CrmDeal.assigned_by_id == manager_id)

    deals = (
        await session.execute(
            select(CrmDeal)
            .where(*filters)
            .options(selectinload(CrmDeal.stage), selectinload(CrmDeal.assigned_manager))
        )
    ).scalars().all()

    # Lost after long silence (objective fact, not SLA): failure + ≥14d without observed activity before close
    lost_candidates = (
        await session.execute(
            select(CrmDeal)
            .join(CrmStage, CrmDeal.stage_id == CrmStage.id, isouter=True)
            .where(
                CrmDeal.closed.is_(True),
                CrmDeal.missing_from_bitrix.is_(False),
                CrmStage.semantics == "failure",
            )
            .options(selectinload(CrmDeal.stage), selectinload(CrmDeal.assigned_manager))
            .order_by(CrmDeal.closedate.desc().nullslast())
            .limit(200)
        )
    ).scalars().all()
    lost_items: list[dict[str, Any]] = []
    for d in lost_candidates:
        close_ts = _as_utc(d.closedate or d.date_modify)
        act_ts = _as_utc(d.last_observed_activity_at)
        if close_ts is None:
            continue
        if act_ts is None:
            fact = "Потеряна без наблюдаемых дел"
        else:
            gap_days = (close_ts - act_ts).total_seconds() / 86400
            if gap_days < 14:
                continue
            fact = f"Потеряна после {int(gap_days)} д. без наблюдаемых действий"
        lost_items.append(_deal_item(d, category="lost_after_silence", fact=fact, now=now))
        if len(lost_items) >= 20:
            break

    categories: dict[str, list[dict[str, Any]]] = {
        "no_future_activity": [],
        "overdue_activity": [],
        "no_observed_movement": [],
        "overdue_next_contact": [],
        "lost_after_silence": lost_items[:20],
        "money_at_risk": [],
    }

    for d in deals:
        mgr = (
            f"{d.assigned_manager.name} {d.assigned_manager.last_name}".strip()
            if d.assigned_manager
            else None
        )
        base = {
            "deal_id": d.id,
            "bitrix_id": d.bitrix_id,
            "title": d.title,
            "manager": mgr,
            "manager_id": d.assigned_by_id,
            "stage": d.stage.name if d.stage else None,
            "pipeline_category_id": d.category_id,
            "amount": float(d.opportunity) if d.opportunity is not None else None,
            "has_future_activity": d.has_future_activity,
        }
        needs_attention = False

        if not d.has_future_activity:
            categories["no_future_activity"].append(
                {
                    **base,
                    "category": "no_future_activity",
                    "fact": "Нет следующего дела",
                }
            )
            needs_attention = True

        act = overdue_by_owner.get(d.bitrix_id)
        if act and act.deadline:
            overdue_s = (now - _as_utc(act.deadline)).total_seconds()  # type: ignore[arg-type]
            fact = f"Просрочено дело на {format_duration(overdue_s)}"
            item = {**base, "category": "overdue_activity", "fact": fact, "activity_id": act.id, "deadline": act.deadline.isoformat()}
            categories["overdue_activity"].append(item)
            categories["overdue_next_contact"].append(item)
            needs_attention = True

        ref = _as_utc(d.last_observed_activity_at or d.stage_changed_observed_at or d.date_modify)
        if ref is not None:
            idle_s = (now - ref).total_seconds()
            if idle_s >= 2 * 86400:  # objective display threshold for "давно" — not a business SLA rule
                categories["no_observed_movement"].append(
                    {
                        **base,
                        "category": "no_observed_movement",
                        "fact": f"Последнее наблюдаемое изменение {format_duration(idle_s)} назад",
                        "observed_note": "Время наблюдения системой (polling), не точный Bitrix event time",
                    }
                )
                needs_attention = True

        if needs_attention:
            categories["money_at_risk"].append(
                {
                    **base,
                    "category": "money_at_risk",
                    "fact": "Требует внимания",
                }
            )

    # Cap lists for payload size
    for key in categories:
        categories[key] = categories[key][:limit]

    from app.services.sales_rules.aggregates import business_rule_attention

    business = await business_rule_attention(session, limit=limit)

    return {
        "title": "Требуют внимания",
        "money_requiring_attention": money,
        "objective_signals": {
            "label": "OBJECTIVE SIGNALS",
            "categories": {
                "no_future_activity": {
                    "label": "Нет следующего дела",
                    "count": len(categories["no_future_activity"]),
                    "items": categories["no_future_activity"],
                },
                "overdue_activity": {
                    "label": "Есть просроченное дело",
                    "count": len(categories["overdue_activity"]),
                    "items": categories["overdue_activity"],
                },
                "no_observed_movement": {
                    "label": "Давно не было наблюдаемого движения",
                    "count": len(categories["no_observed_movement"]),
                    "items": categories["no_observed_movement"],
                    "note": "Порог отображения 2 дня — факт для UI, не утверждённый SLA",
                },
                "overdue_next_contact": {
                    "label": "Просрочен следующий контакт",
                    "count": len(categories["overdue_next_contact"]),
                    "items": categories["overdue_next_contact"],
                },
                "lost_after_silence": {
                    "label": "Потеряна после длительного отсутствия действий",
                    "count": len(categories["lost_after_silence"]),
                    "items": categories["lost_after_silence"],
                },
                "money_at_risk": {
                    "label": "Потенциально зависшие деньги",
                    "count": len(categories["money_at_risk"]),
                    "items": categories["money_at_risk"][:limit],
                },
            },
        },
        "business_rule_violations": {
            "label": "BUSINESS RULE VIOLATIONS",
            **business,
        },
        # Backward-compatible flat categories (objective only)
        "categories": {
            "no_future_activity": {
                "label": "Нет следующего дела",
                "count": len(categories["no_future_activity"]),
                "items": categories["no_future_activity"],
            },
            "overdue_activity": {
                "label": "Есть просроченное дело",
                "count": len(categories["overdue_activity"]),
                "items": categories["overdue_activity"],
            },
            "no_observed_movement": {
                "label": "Давно не было наблюдаемого движения",
                "count": len(categories["no_observed_movement"]),
                "items": categories["no_observed_movement"],
                "note": "Порог отображения 2 дня — факт для UI, не утверждённый SLA",
            },
            "overdue_next_contact": {
                "label": "Просрочен следующий контакт",
                "count": len(categories["overdue_next_contact"]),
                "items": categories["overdue_next_contact"],
            },
            "lost_after_silence": {
                "label": "Потеряна после длительного отсутствия действий",
                "count": len(categories["lost_after_silence"]),
                "items": categories["lost_after_silence"],
            },
            "money_at_risk": {
                "label": "Потенциально зависшие деньги",
                "count": len(categories["money_at_risk"]),
                "items": categories["money_at_risk"][:limit],
            },
        },
        "rules_note": business.get("note")
        or "Объективные сигналы работают независимо от sales rules.",
    }


def _deal_item(d: CrmDeal, *, category: str, fact: str, now: datetime) -> dict[str, Any]:
    return {
        "deal_id": d.id,
        "bitrix_id": d.bitrix_id,
        "title": d.title,
        "manager": (
            f"{d.assigned_manager.name} {d.assigned_manager.last_name}".strip()
            if d.assigned_manager
            else None
        ),
        "manager_id": d.assigned_by_id,
        "stage": d.stage.name if d.stage else None,
        "pipeline_category_id": d.category_id,
        "amount": float(d.opportunity) if d.opportunity is not None else None,
        "category": category,
        "fact": fact,
        "has_future_activity": d.has_future_activity,
    }

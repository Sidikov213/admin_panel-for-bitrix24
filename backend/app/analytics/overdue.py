"""Overdue activities over a period: still open ones and ones closed after the deadline."""

from __future__ import annotations

import statistics
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, or_, select

from app.analytics.kpi import _as_utc
from app.core.timezone import local_day_bounds, utc_now
from app.integrations.bitrix.links import activity_type_label, deal_url
from app.models.crm import CrmActivity, CrmDeal, CrmManager, CrmPipeline, CrmStage


async def overdue_report(
    session,
    *,
    date_from: date,
    date_to: date,
    manager_id: int | None = None,
    category_id: int | None = None,
    stage_id: int | None = None,
    only_open: bool = False,
    offset: int = 0,
    limit: int = 50,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Activities whose deadline fell in [date_from, date_to] and was missed.

    Missed = deadline passed while the activity was still open: either it is open now, or it
    was completed after the deadline. Completed ones with an unknown completion moment are
    counted separately and not listed (see migration 0005).
    """
    now = now or utc_now()
    start_utc, _ = local_day_bounds(date_from)
    _, end_utc = local_day_bounds(date_to)
    base = (
        select(CrmActivity, CrmDeal, CrmStage, CrmManager, CrmPipeline)
        .join(CrmDeal, (CrmDeal.bitrix_id == CrmActivity.owner_id) & (CrmActivity.owner_type_id == 2))
        .outerjoin(CrmStage, CrmStage.id == CrmDeal.stage_id)
        .outerjoin(CrmManager, CrmManager.id == CrmDeal.assigned_by_id)
        .outerjoin(CrmPipeline, CrmPipeline.bitrix_id == CrmDeal.category_id)
        .where(
            CrmDeal.missing_from_bitrix.is_(False),
            CrmActivity.deadline.isnot(None),
            CrmActivity.deadline >= start_utc,
            CrmActivity.deadline <= end_utc,
            CrmActivity.deadline < now,
        )
    )
    if manager_id is not None:
        base = base.where(CrmDeal.assigned_by_id == manager_id)
    if category_id is not None:
        base = base.where(CrmDeal.category_id == category_id)
    if stage_id is not None:
        base = base.where(CrmDeal.stage_id == stage_id)

    missed = or_(
        CrmActivity.completed.is_(False),
        and_(CrmActivity.completed_at.isnot(None), CrmActivity.completed_at > CrmActivity.deadline),
    )
    unknown = (
        await session.execute(
            base.with_only_columns(CrmActivity.id).where(
                CrmActivity.completed.is_(True), CrmActivity.completed_at.is_(None)
            )
        )
    ).all()
    rows = (await session.execute(base.where(missed))).all()

    items: list[dict[str, Any]] = []
    close_delays: list[float] = []
    for act, deal, stage, mgr, pipe in rows:
        deadline = _as_utc(act.deadline)
        done = _as_utc(act.completed_at) if act.completed else None
        overdue_seconds = ((done or now) - deadline).total_seconds()
        if done:
            close_delays.append(overdue_seconds)
        items.append(
            {
                "activity_id": act.id,
                "bitrix_id": act.bitrix_id,
                "type": activity_type_label(act.type_id),
                "subject": act.subject,
                "deadline": deadline.isoformat(),
                "is_open": not act.completed,
                "completed_at": done.isoformat() if done else None,
                "overdue_seconds": round(overdue_seconds),
                "deal_id": deal.id,
                "deal_bitrix_id": deal.bitrix_id,
                "deal_title": deal.title,
                "manager_id": deal.assigned_by_id,
                "manager": f"{mgr.last_name} {mgr.name}".strip() if mgr else None,
                "pipeline": pipe.name if pipe else None,
                "stage": stage.name if stage else None,
                "bitrix_url": deal_url(deal.bitrix_id),
            }
        )
    open_count = sum(i["is_open"] for i in items)
    summary = {
        "total": len(items),
        "open": open_count,
        "closed_late": len(items) - open_count,
        "close_delay_median_seconds": round(statistics.median(close_delays)) if close_delays else None,
        "close_delay_avg_seconds": round(statistics.fmean(close_delays)) if close_delays else None,
        "unknown_completion": len(unknown),
    }
    if only_open:
        items = [i for i in items if i["is_open"]]
    # Still hanging first, longest overdue first
    items.sort(key=lambda i: (not i["is_open"], -i["overdue_seconds"]))
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "summary": summary,
        "items": items[offset : offset + limit],
        "total": len(items),
        "offset": offset,
        "limit": limit,
        "computed_at": now.isoformat(),
    }

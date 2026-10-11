from datetime import date, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.analytics.attention import format_duration
from app.auth.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.timezone import local_day_bounds, utc_now
from app.models.crm import CrmActivity, CrmDeal

router = APIRouter()


@router.get("")
async def list_overdue(
    _user: CurrentUser,
    db: DbSession,
    manager_id: int | None = Query(default=None),
    pipeline_id: int | None = Query(default=None, description="Bitrix category_id"),
    stage_id: int | None = Query(default=None),
    min_overdue_minutes: int | None = Query(default=None),
    max_overdue_minutes: int | None = Query(default=None),
    date_from: date | None = Query(default=None, description="Deadline from"),
    date_to: date | None = Query(default=None, description="Deadline to"),
    group_by: str | None = Query(default=None, description="manager|pipeline"),
) -> dict:
    now = utc_now()
    stmt = select(CrmActivity).where(
        CrmActivity.completed.is_(False),
        CrmActivity.deadline.isnot(None),
        CrmActivity.deadline < now,
    )
    if date_from is not None:
        start_utc, _ = local_day_bounds(date_from)
        stmt = stmt.where(CrmActivity.deadline >= start_utc)
    if date_to is not None:
        _, end_utc = local_day_bounds(date_to)
        stmt = stmt.where(CrmActivity.deadline <= end_utc)

    rows = (await db.execute(stmt.order_by(CrmActivity.deadline.asc()))).scalars().unique().all()
    owner_ids = {a.owner_id for a in rows if a.owner_id is not None}
    deals_by_bx: dict[int, CrmDeal] = {}
    if owner_ids:
        deals = (
            await db.execute(
                select(CrmDeal)
                .where(CrmDeal.bitrix_id.in_(owner_ids))
                .options(selectinload(CrmDeal.stage), selectinload(CrmDeal.assigned_manager))
            )
        ).scalars().all()
        deals_by_bx = {d.bitrix_id: d for d in deals}

    settings = get_settings()
    portal = (settings.BITRIX_PORTAL_URL or "").rstrip("/")

    seen: set[int] = set()
    items = []
    for a in rows:
        if a.bitrix_id in seen:
            continue
        seen.add(a.bitrix_id)
        deal = deals_by_bx.get(a.owner_id) if a.owner_id else None
        if manager_id is not None and (deal is None or deal.assigned_by_id != manager_id):
            continue
        if pipeline_id is not None and (deal is None or deal.category_id != pipeline_id):
            continue
        if stage_id is not None and (deal is None or deal.stage_id != stage_id):
            continue

        overdue_s = (now - a.deadline).total_seconds() if a.deadline else 0  # type: ignore[operator]
        overdue_min = int(overdue_s // 60)
        if min_overdue_minutes is not None and overdue_min < min_overdue_minutes:
            continue
        if max_overdue_minutes is not None and overdue_min > max_overdue_minutes:
            continue

        items.append(
            {
                "id": a.id,
                "bitrix_id": a.bitrix_id,
                "subject": a.subject,
                "deadline": a.deadline.isoformat() if a.deadline else None,
                "overdue_seconds": int(overdue_s),
                "overdue_label": format_duration(overdue_s),
                "manager_id": deal.assigned_by_id if deal else None,
                "manager": (
                    f"{deal.assigned_manager.name} {deal.assigned_manager.last_name}".strip()
                    if deal and deal.assigned_manager
                    else None
                ),
                "deal_id": deal.id if deal else None,
                "deal_title": deal.title if deal else None,
                "deal_bitrix_id": deal.bitrix_id if deal else a.owner_id,
                "pipeline_category_id": deal.category_id if deal else None,
                "stage": deal.stage.name if deal and deal.stage else None,
                "stage_id": deal.stage_id if deal else None,
                "amount": float(deal.opportunity) if deal and deal.opportunity is not None else None,
                "bitrix_url": (
                    f"{portal}/crm/deal/details/{deal.bitrix_id}/" if portal and deal else None
                ),
            }
        )

    groups: dict[str, list] | None = None
    if group_by == "manager":
        groups = {}
        for it in items:
            key = it.get("manager") or "Не назначен"
            groups.setdefault(key, []).append(it)
    elif group_by == "pipeline":
        groups = {}
        for it in items:
            key = str(it.get("pipeline_category_id") or "unknown")
            groups.setdefault(key, []).append(it)

    return {
        "items": items,
        "total": len(items),
        "groups": groups,
        "note": "1 Bitrix activity = 1 overdue activity (deduped by bitrix_id)",
    }

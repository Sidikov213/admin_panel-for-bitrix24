from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from sqlalchemy import case, func, select

from app.analytics.kpi import compute_manager_stats, overdue_activities_query
from app.auth.csrf import validate_csrf
from app.auth.deps import AdminUser, CurrentUser, DbSession
from app.core.timezone import local_day_bounds, utc_now
from app.models.crm import CrmActivity, CrmDeal, CrmManager, CrmStage
from app.schemas.deals import ManagerBrief, ManagerUpdate

router = APIRouter()


@router.get("")
async def list_managers(_user: CurrentUser, db: DbSession) -> list[dict]:
    """Batch SQL metrics — no per-manager compute_period_kpis (N+1)."""
    rows = (await db.execute(select(CrmManager).order_by(CrmManager.last_name))).scalars().all()
    if not rows:
        return []

    today = date.today()
    period_start = today - timedelta(days=29)
    start_utc, _ = local_day_bounds(period_start)
    _, end_utc = local_day_bounds(today)
    now = utc_now()

    deal_agg = (
        await db.execute(
            select(
                CrmDeal.assigned_by_id,
                func.count()
                .filter(CrmDeal.closed.is_(False), CrmDeal.missing_from_bitrix.is_(False))
                .label("active"),
                func.count()
                .filter(
                    CrmDeal.closed.is_(False),
                    CrmDeal.missing_from_bitrix.is_(False),
                    CrmDeal.has_future_activity.is_(False),
                )
                .label("no_future"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (CrmDeal.closed.is_(False)) & (CrmDeal.missing_from_bitrix.is_(False)),
                                CrmDeal.opportunity,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("sum_active"),
                func.count()
                .filter(
                    CrmDeal.missing_from_bitrix.is_(False),
                    CrmDeal.date_create >= start_utc,
                    CrmDeal.date_create <= end_utc,
                )
                .label("new_count"),
            )
            .where(CrmDeal.assigned_by_id.isnot(None))
            .group_by(CrmDeal.assigned_by_id)
        )
    ).all()
    by_mgr = {
        mid: {
            "active": int(active or 0),
            "no_future": int(no_future or 0),
            "sum_active": float(sum_active or 0),
            "new_count": int(new_count or 0),
        }
        for mid, active, no_future, sum_active, new_count in deal_agg
    }

    # Won in period by manager (CLOSEDATE or date_modify fallback)
    won_rows = (
        await db.execute(
            select(CrmDeal.assigned_by_id, CrmDeal.opportunity, CrmDeal.closedate, CrmDeal.date_modify)
            .join(CrmStage, CrmDeal.stage_id == CrmStage.id, isouter=True)
            .where(
                CrmDeal.closed.is_(True),
                CrmDeal.missing_from_bitrix.is_(False),
                CrmStage.semantics == "success",
                CrmDeal.assigned_by_id.isnot(None),
            )
        )
    ).all()
    won_by_mgr: dict[int, dict[str, float | int]] = {}
    for mid, opp, closedate, date_modify in won_rows:
        ts = closedate or date_modify
        if ts is None:
            continue
        if ts.tzinfo is None:
            from datetime import timezone

            ts = ts.replace(tzinfo=timezone.utc)
        if not (start_utc <= ts <= end_utc):
            continue
        bucket = won_by_mgr.setdefault(mid, {"won_count": 0, "sum_won": 0.0})
        bucket["won_count"] = int(bucket["won_count"]) + 1
        bucket["sum_won"] = float(bucket["sum_won"]) + float(opp or 0)

    overdue_rows = (
        await db.execute(
            overdue_activities_query(now, CrmDeal.assigned_by_id, CrmActivity.bitrix_id).where(
                CrmDeal.assigned_by_id.isnot(None)
            )
        )
    ).all()
    overdue_by_mgr: dict[int, set[int]] = {}
    for mid, act_bid in overdue_rows:
        overdue_by_mgr.setdefault(mid, set()).add(act_bid)

    result = []
    for r in rows:
        m = by_mgr.get(r.id, {"active": 0, "no_future": 0, "sum_active": 0.0, "new_count": 0})
        w = won_by_mgr.get(r.id, {"won_count": 0, "sum_won": 0.0})
        result.append(
            {
                **ManagerBrief.model_validate(r).model_dump(),
                "active_deals_count": m["active"],
                "new_deals_count": m["new_count"],
                "won_count": w["won_count"],
                "sum_active_opportunity": m["sum_active"],
                "sum_won_opportunity": w["sum_won"],
                "overdue_activities_unique": len(overdue_by_mgr.get(r.id, set())),
                "deals_without_future_activity_count": m["no_future"],
            }
        )
    return result


@router.get("/{manager_id}")
async def get_manager(
    manager_id: int,
    _user: CurrentUser,
    db: DbSession,
    period_start: date | None = Query(default=None),
    period_end: date | None = Query(default=None),
) -> dict:
    row = await db.get(CrmManager, manager_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found")
    today = date.today()
    end = period_end or today
    start = period_start or (end - timedelta(days=29))
    stats = await compute_manager_stats(db, manager_id, start, end)
    return {
        "manager": ManagerBrief.model_validate(row).model_dump(),
        **stats,
    }


@router.patch("/{manager_id}", response_model=ManagerBrief)
async def update_manager(
    manager_id: int,
    body: ManagerUpdate,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> ManagerBrief:
    """Panel-only fields; Bitrix data of the manager stays read-only."""
    validate_csrf(request, csrf_header)
    row = await db.get(CrmManager, manager_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found")
    if "telegram_chat_id" in body.model_fields_set:
        row.telegram_chat_id = body.telegram_chat_id
    await db.flush()
    return ManagerBrief.model_validate(row)

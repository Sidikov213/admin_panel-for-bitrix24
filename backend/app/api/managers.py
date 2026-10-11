from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import selectinload

from app.analytics.compare import compare_kpi_dicts
from app.analytics.kpi import compute_manager_stats, compute_period_kpis
from app.analytics.periods import resolve_period
from app.auth.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.timezone import local_day_bounds, utc_now
from app.models.crm import CrmActivity, CrmDeal, CrmManager, CrmStage, DealChangeEvent
from app.schemas.deals import ManagerBrief
from app.services.targets_service import TargetsService

router = APIRouter()


@router.get("")
async def list_managers(
    _user: CurrentUser,
    db: DbSession,
    period_start: date | None = Query(default=None),
    period_end: date | None = Query(default=None),
    preset: str | None = Query(default=None),
) -> list[dict]:
    """Batch SQL metrics — no per-manager compute_period_kpis (N+1)."""
    rng = resolve_period(preset=preset, period_start=period_start, period_end=period_end)
    rows = (await db.execute(select(CrmManager).order_by(CrmManager.last_name))).scalars().all()
    if not rows:
        return []

    start_utc, _ = local_day_bounds(rng.start)
    _, end_utc = local_day_bounds(rng.end)
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

    closed_rows = (
        await db.execute(
            select(
                CrmDeal.assigned_by_id,
                CrmDeal.opportunity,
                CrmDeal.closedate,
                CrmDeal.date_modify,
                CrmStage.semantics,
            )
            .join(CrmStage, CrmDeal.stage_id == CrmStage.id, isouter=True)
            .where(
                CrmDeal.closed.is_(True),
                CrmDeal.missing_from_bitrix.is_(False),
                CrmStage.semantics.in_(("success", "failure")),
                CrmDeal.assigned_by_id.isnot(None),
            )
        )
    ).all()
    won_by_mgr: dict[int, dict[str, float | int]] = {}
    lost_by_mgr: dict[int, int] = {}
    for mid, opp, closedate, date_modify, sem in closed_rows:
        ts = closedate or date_modify
        if ts is None:
            continue
        if ts.tzinfo is None:
            from datetime import timezone

            ts = ts.replace(tzinfo=timezone.utc)
        if not (start_utc <= ts <= end_utc):
            continue
        if sem == "success":
            bucket = won_by_mgr.setdefault(mid, {"won_count": 0, "sum_won": 0.0})
            bucket["won_count"] = int(bucket["won_count"]) + 1
            bucket["sum_won"] = float(bucket["sum_won"]) + float(opp or 0)
        elif sem == "failure":
            lost_by_mgr[mid] = lost_by_mgr.get(mid, 0) + 1

    stage_change_rows = (
        await db.execute(
            select(CrmDeal.assigned_by_id, func.count())
            .join(DealChangeEvent, DealChangeEvent.deal_id == CrmDeal.id)
            .where(
                DealChangeEvent.field_name == "stage_id",
                DealChangeEvent.observed_at >= start_utc,
                DealChangeEvent.observed_at <= end_utc,
                CrmDeal.assigned_by_id.isnot(None),
            )
            .group_by(CrmDeal.assigned_by_id)
        )
    ).all()
    stage_changes = {mid: int(cnt) for mid, cnt in stage_change_rows}

    overdue_rows = (
        await db.execute(
            select(CrmDeal.assigned_by_id, CrmActivity.bitrix_id)
            .join(CrmDeal, CrmDeal.bitrix_id == CrmActivity.owner_id)
            .where(
                CrmActivity.completed.is_(False),
                CrmActivity.deadline.isnot(None),
                CrmActivity.deadline < now,
                CrmDeal.missing_from_bitrix.is_(False),
                CrmDeal.assigned_by_id.isnot(None),
            )
        )
    ).all()
    overdue_by_mgr: dict[int, set[int]] = {}
    for mid, act_bid in overdue_rows:
        overdue_by_mgr.setdefault(mid, set()).add(act_bid)

    # Previous period for deltas (compact — only key metrics)
    prev = rng.previous()
    prev_start, _ = local_day_bounds(prev.start)
    _, prev_end = local_day_bounds(prev.end)
    prev_new_rows = (
        await db.execute(
            select(CrmDeal.assigned_by_id, func.count())
            .where(
                CrmDeal.assigned_by_id.isnot(None),
                CrmDeal.missing_from_bitrix.is_(False),
                CrmDeal.date_create >= prev_start,
                CrmDeal.date_create <= prev_end,
            )
            .group_by(CrmDeal.assigned_by_id)
        )
    ).all()
    prev_new = {mid: int(c) for mid, c in prev_new_rows}

    from app.services.sales_rules.aggregates import manager_violation_stats

    viol_by_mgr = await manager_violation_stats(
        db, period_start=rng.start, period_end=rng.end
    )

    result = []
    for r in rows:
        m = by_mgr.get(r.id, {"active": 0, "no_future": 0, "sum_active": 0.0, "new_count": 0})
        w = won_by_mgr.get(r.id, {"won_count": 0, "sum_won": 0.0})
        active = m["active"]
        no_future = m["no_future"]
        new_count = m["new_count"]
        prev_n = prev_new.get(r.id, 0)
        v = viol_by_mgr.get(r.id, {})
        result.append(
            {
                **ManagerBrief.model_validate(r).model_dump(),
                "active_deals_count": active,
                "new_deals_count": new_count,
                "won_count": w["won_count"],
                "lost_count": lost_by_mgr.get(r.id, 0),
                "sum_active_opportunity": m["sum_active"],
                "sum_won_opportunity": w["sum_won"],
                "overdue_activities_unique": len(overdue_by_mgr.get(r.id, set())),
                "deals_without_future_activity_count": no_future,
                "no_future_share": round(no_future / active * 100.0, 1) if active else 0.0,
                "observed_stage_changes": stage_changes.get(r.id, 0),
                "open_violations": v.get("open_violations", 0),
                "high_severity_violations": v.get("high_severity_violations", 0),
                "resolved_violations": v.get("resolved_violations", 0),
                "violation_rate": v.get("violation_rate"),
                "new_deals_delta": {
                    "current": new_count,
                    "previous": prev_n,
                    "abs_delta": new_count - prev_n,
                    "pct_delta": (
                        round((new_count - prev_n) / prev_n * 100.0, 1) if prev_n else None
                    ),
                },
                "period": {"start": rng.start.isoformat(), "end": rng.end.isoformat(), "preset": rng.preset},
            }
        )
    return result


@router.get("/{manager_id}/deals")
async def manager_deals_drilldown(
    manager_id: int,
    _user: CurrentUser,
    db: DbSession,
    metric: str = Query(
        ...,
        description="active|new|won|lost|no_future|overdue",
    ),
    period_start: date | None = Query(default=None),
    period_end: date | None = Query(default=None),
    preset: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> dict:
    row = await db.get(CrmManager, manager_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found")
    rng = resolve_period(preset=preset, period_start=period_start, period_end=period_end)
    start_utc, _ = local_day_bounds(rng.start)
    _, end_utc = local_day_bounds(rng.end)
    now = utc_now()
    settings = get_settings()
    portal = (settings.BITRIX_PORTAL_URL or "").rstrip("/")

    base = select(CrmDeal).where(
        CrmDeal.assigned_by_id == manager_id,
        CrmDeal.missing_from_bitrix.is_(False),
    ).options(selectinload(CrmDeal.stage))

    if metric == "active":
        stmt = base.where(CrmDeal.closed.is_(False))
    elif metric == "new":
        stmt = base.where(CrmDeal.date_create >= start_utc, CrmDeal.date_create <= end_utc)
    elif metric == "won":
        stmt = (
            base.join(CrmStage, CrmDeal.stage_id == CrmStage.id, isouter=True)
            .where(CrmDeal.closed.is_(True), CrmStage.semantics == "success")
        )
    elif metric == "lost":
        stmt = (
            base.join(CrmStage, CrmDeal.stage_id == CrmStage.id, isouter=True)
            .where(CrmDeal.closed.is_(True), CrmStage.semantics == "failure")
        )
    elif metric == "no_future":
        stmt = base.where(CrmDeal.closed.is_(False), CrmDeal.has_future_activity.is_(False))
    elif metric == "overdue":
        owner_ids = (
            await db.execute(
                select(CrmActivity.owner_id)
                .where(
                    CrmActivity.completed.is_(False),
                    CrmActivity.deadline.isnot(None),
                    CrmActivity.deadline < now,
                    CrmActivity.owner_id.isnot(None),
                )
                .distinct()
            )
        ).scalars().all()
        stmt = base.where(CrmDeal.closed.is_(False), CrmDeal.bitrix_id.in_(list(owner_ids)))
    else:
        raise HTTPException(status_code=400, detail="Unknown metric")

    deals = (await db.execute(stmt.order_by(CrmDeal.date_modify.desc().nullslast()).limit(limit))).scalars().all()

    # Filter won/lost to period in Python (CLOSEDATE fallback)
    if metric in ("won", "lost"):
        filtered = []
        for d in deals:
            ts = d.closedate or d.date_modify
            if ts is None:
                continue
            if ts.tzinfo is None:
                from datetime import timezone

                ts = ts.replace(tzinfo=timezone.utc)
            if start_utc <= ts <= end_utc:
                filtered.append(d)
        deals = filtered

    return {
        "manager_id": manager_id,
        "metric": metric,
        "period": {"start": rng.start.isoformat(), "end": rng.end.isoformat()},
        "items": [
            {
                "id": d.id,
                "bitrix_id": d.bitrix_id,
                "title": d.title,
                "closed": d.closed,
                "opportunity": float(d.opportunity) if d.opportunity is not None else None,
                "stage_name": d.stage.name if d.stage else None,
                "has_future_activity": d.has_future_activity,
                "bitrix_url": f"{portal}/crm/deal/details/{d.bitrix_id}/" if portal else None,
            }
            for d in deals
        ],
        "total": len(deals),
    }


@router.get("/{manager_id}")
async def get_manager(
    manager_id: int,
    _user: CurrentUser,
    db: DbSession,
    period_start: date | None = Query(default=None),
    period_end: date | None = Query(default=None),
    preset: str | None = Query(default=None),
) -> dict:
    row = await db.get(CrmManager, manager_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found")
    rng = resolve_period(preset=preset, period_start=period_start, period_end=period_end)
    prev = rng.previous()
    stats = await compute_manager_stats(db, manager_id, rng.start, rng.end)
    prev_kpis = await compute_period_kpis(
        db, prev.start, prev.end, manager_id=manager_id, include_series=False
    )
    comparison = compare_kpi_dicts(stats["kpis"], prev_kpis)
    plan_fact = await TargetsService(db).plan_fact_for_range(rng.start, rng.end, manager_id=manager_id)

    from app.services.sales_rules.aggregates import manager_violation_stats

    viol = (await manager_violation_stats(db, manager_id=manager_id, period_start=rng.start, period_end=rng.end)).get(
        manager_id, {}
    )

    # Problem deals for this manager
    now = utc_now()
    problems = (
        await db.execute(
            select(CrmDeal)
            .where(
                CrmDeal.assigned_by_id == manager_id,
                CrmDeal.closed.is_(False),
                CrmDeal.missing_from_bitrix.is_(False),
                CrmDeal.has_future_activity.is_(False),
            )
            .options(selectinload(CrmDeal.stage))
            .limit(50)
        )
    ).scalars().all()
    settings = get_settings()
    portal = (settings.BITRIX_PORTAL_URL or "").rstrip("/")

    return {
        "manager": ManagerBrief.model_validate(row).model_dump(),
        **stats,
        "comparison": {
            "current_period": {"start": rng.start.isoformat(), "end": rng.end.isoformat()},
            "previous_period": {"start": prev.start.isoformat(), "end": prev.end.isoformat()},
            "metrics": comparison,
        },
        "plan_fact": plan_fact,
        "open_violations": viol.get("open_violations", 0),
        "high_severity_violations": viol.get("high_severity_violations", 0),
        "resolved_violations": viol.get("resolved_violations", 0),
        "violation_rate": viol.get("violation_rate"),
        "problem_deals": [
            {
                "id": d.id,
                "bitrix_id": d.bitrix_id,
                "title": d.title,
                "stage_name": d.stage.name if d.stage else None,
                "opportunity": float(d.opportunity) if d.opportunity is not None else None,
                "fact": "Нет следующего дела",
                "bitrix_url": f"{portal}/crm/deal/details/{d.bitrix_id}/" if portal else None,
            }
            for d in problems
        ],
        "meta": {"period_start": rng.start.isoformat(), "period_end": rng.end.isoformat(), "preset": rng.preset},
    }

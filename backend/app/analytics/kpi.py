from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.timezone import app_tz, local_day_bounds, utc_now
from app.models.crm import CrmActivity, CrmDeal, CrmManager, CrmPipeline, CrmStage, DealChangeEvent


def _decimal_sum(values: list[Decimal | None]) -> Decimal:
    total = Decimal("0")
    for v in values:
        if v is not None:
            total += v
    return total


def _as_utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


KPI_DEFINITIONS: dict[str, dict[str, str]] = {
    "new_deals_count": {
        "label": "Новые сделки",
        "formula": "Сделки с DATE_CREATE в выбранном периоде (часовой пояс Europe/Moscow)",
        "source": "crm_deals.date_create (Bitrix)",
    },
    "active_deals_count": {
        "label": "Активные сделки",
        "formula": "Сделки с closed=false на момент расчёта",
        "source": "crm_deals.closed",
    },
    "won_count": {
        "label": "Успешно закрыто",
        "formula": "closed=true, семантика этапа success, CLOSEDATE в периоде",
        "source": "crm_deals + crm_stages.semantics",
    },
    "lost_count": {
        "label": "Проигранные",
        "formula": "closed=true, семантика этапа failure, CLOSEDATE в периоде",
        "source": "crm_deals + crm_stages.semantics",
    },
    "sum_active_opportunity": {
        "label": "Сумма в работе",
        "formula": "SUM(opportunity) по активным сделкам",
        "source": "crm_deals.opportunity",
    },
    "sum_won_opportunity": {
        "label": "Сумма успешно закрытых",
        "formula": "SUM(opportunity) по won-сделкам за период",
        "source": "crm_deals.opportunity",
    },
    "overdue_activities_unique": {
        "label": "Просроченные дела",
        "formula": "Уникальные crm_activities: deadline < now AND completed=false",
        "source": "crm_activities",
    },
    "deals_without_future_activity_count": {
        "label": "Без следующего дела",
        "formula": "Активные сделки с has_future_activity=false (факт, не SLA)",
        "source": "crm_deals.has_future_activity",
    },
}


async def compute_period_kpis(
    session: AsyncSession,
    period_start: date,
    period_end: date,
    pipeline_id: int | None = None,
    manager_id: int | None = None,
    *,
    include_series: bool = True,
) -> dict[str, Any]:
    start_utc, _ = local_day_bounds(period_start)
    _, end_utc = local_day_bounds(period_end)
    now = utc_now()

    deal_filters = [CrmDeal.missing_from_bitrix.is_(False)]
    if pipeline_id is not None:
        deal_filters.append(CrmDeal.category_id == pipeline_id)
    if manager_id is not None:
        deal_filters.append(CrmDeal.assigned_by_id == manager_id)

    base = select(CrmDeal).where(*deal_filters)

    new_deals = (
        await session.execute(
            base.where(CrmDeal.date_create >= start_utc, CrmDeal.date_create <= end_utc)
        )
    ).scalars().all()

    active_deals = (await session.execute(base.where(CrmDeal.closed.is_(False)))).scalars().all()

    # Prefer CLOSEDATE in period; if Bitrix CLOSEDATE missing, fall back to date_modify
    # and mark data_quality — do not invent event timestamps.
    won_candidates = (
        await session.execute(
            select(CrmDeal)
            .join(CrmStage, CrmDeal.stage_id == CrmStage.id, isouter=True)
            .where(CrmDeal.closed.is_(True), CrmStage.semantics == "success", *deal_filters)
        )
    ).scalars().all()
    lost_candidates = (
        await session.execute(
            select(CrmDeal)
            .join(CrmStage, CrmDeal.stage_id == CrmStage.id, isouter=True)
            .where(CrmDeal.closed.is_(True), CrmStage.semantics == "failure", *deal_filters)
        )
    ).scalars().all()

    def _in_period(d: CrmDeal) -> bool:
        ts = _as_utc(d.closedate or d.date_modify)
        return bool(ts and start_utc <= ts <= end_utc)

    won_deals = [d for d in won_candidates if _in_period(d)]
    lost_deals = [d for d in lost_candidates if _in_period(d)]
    won_missing_closedate = sum(1 for d in won_deals if d.closedate is None)

    stages_with_semantics = (
        await session.execute(select(func.count()).select_from(CrmStage).where(CrmStage.semantics.isnot(None)))
    ).scalar_one()
    insufficient_stage_semantics = stages_with_semantics == 0

    overdue_q = select(CrmActivity.bitrix_id).where(
        CrmActivity.completed.is_(False),
        CrmActivity.deadline.isnot(None),
        CrmActivity.deadline < now,
    )
    if manager_id is not None or pipeline_id is not None:
        overdue_q = (
            overdue_q.join(CrmDeal, CrmDeal.bitrix_id == CrmActivity.owner_id)
            .where(CrmDeal.missing_from_bitrix.is_(False))
        )
        if manager_id is not None:
            overdue_q = overdue_q.where(CrmDeal.assigned_by_id == manager_id)
        if pipeline_id is not None:
            overdue_q = overdue_q.where(CrmDeal.category_id == pipeline_id)
    overdue_ids = (await session.execute(overdue_q)).scalars().all()
    open_overdue_count = len(set(overdue_ids))

    no_future = (
        await session.execute(
            base.where(CrmDeal.closed.is_(False), CrmDeal.has_future_activity.is_(False))
        )
    ).scalars().all()

    stage_changes = (
        await session.execute(
            select(func.count())
            .select_from(DealChangeEvent)
            .where(
                DealChangeEvent.field_name == "stage_id",
                DealChangeEvent.observed_at >= start_utc,
                DealChangeEvent.observed_at <= end_utc,
            )
        )
    ).scalar_one()

    last_change = (await session.execute(select(func.max(DealChangeEvent.observed_at)))).scalar_one()

    # Enrich stage/manager breakdown with names when available
    stage_ids = {d.stage_id for d in active_deals if d.stage_id}
    stages_map: dict[int, str] = {}
    if stage_ids:
        rows = (await session.execute(select(CrmStage).where(CrmStage.id.in_(stage_ids)))).scalars().all()
        stages_map = {s.id: s.name for s in rows}

    manager_ids = {d.assigned_by_id for d in active_deals if d.assigned_by_id}
    managers_map: dict[int, str] = {}
    if manager_ids:
        rows = (
            await session.execute(select(CrmManager).where(CrmManager.id.in_(manager_ids)))
        ).scalars().all()
        managers_map = {m.id: f"{m.name} {m.last_name}".strip() for m in rows}

    deals_by_stage: dict[str, int] = {}
    deals_by_stage_named: list[dict[str, Any]] = []
    stage_counts: dict[int | None, int] = {}
    for d in active_deals:
        stage_counts[d.stage_id] = stage_counts.get(d.stage_id, 0) + 1
    for sid, cnt in stage_counts.items():
        key = str(sid or "unknown")
        deals_by_stage[key] = cnt
        deals_by_stage_named.append(
            {"stage_id": sid, "name": stages_map.get(sid or -1, "Без этапа"), "count": cnt}
        )

    deals_by_manager: dict[str, int] = {}
    deals_by_manager_named: list[dict[str, Any]] = []
    mgr_counts: dict[int | None, int] = {}
    for d in active_deals:
        mgr_counts[d.assigned_by_id] = mgr_counts.get(d.assigned_by_id, 0) + 1
    for mid, cnt in mgr_counts.items():
        key = str(mid or "unassigned")
        deals_by_manager[key] = cnt
        deals_by_manager_named.append(
            {
                "manager_id": mid,
                "name": managers_map.get(mid or -1, "Не назначен"),
                "count": cnt,
            }
        )

    # Pipeline distribution for active deals
    pipeline_counts: dict[int | None, int] = {}
    for d in active_deals:
        pipeline_counts[d.category_id] = pipeline_counts.get(d.category_id, 0) + 1
    cat_ids = {c for c in pipeline_counts if c is not None}
    pipes_map: dict[int, str] = {}
    if cat_ids:
        # category_id is Bitrix category id stored on deal
        rows = (
            await session.execute(select(CrmPipeline).where(CrmPipeline.bitrix_id.in_(cat_ids)))
        ).scalars().all()
        pipes_map = {p.bitrix_id: p.name for p in rows}
    deals_by_pipeline = [
        {
            "category_id": cid,
            "name": pipes_map.get(cid, f"Воронка {cid}") if cid is not None else "Без воронки",
            "count": cnt,
        }
        for cid, cnt in pipeline_counts.items()
    ]

    series = (
        await _build_daily_series(session, period_start, period_end, deal_filters)
        if include_series
        else []
    )

    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "timezone": str(app_tz()),
        "new_deals_count": len(new_deals),
        "active_deals_count": len(active_deals),
        "won_count": len(won_deals),
        "lost_count": len(lost_deals),
        "sum_active_opportunity": float(_decimal_sum([d.opportunity for d in active_deals])),
        "sum_won_opportunity": float(_decimal_sum([d.opportunity for d in won_deals])),
        "overdue_activities_unique": open_overdue_count,
        "open_overdue": open_overdue_count,
        "deals_by_stage": deals_by_stage,
        "deals_by_stage_named": deals_by_stage_named,
        "deals_by_manager": deals_by_manager,
        "deals_by_manager_named": deals_by_manager_named,
        "deals_by_pipeline": deals_by_pipeline,
        "observed_stage_changes": stage_changes,
        "last_observed_deal_change": last_change.isoformat() if isinstance(last_change, datetime) else None,
        "deals_without_future_activity_count": len(no_future),
        "deals_without_future_activity_label": "нет следующего запланированного дела",
        "series_daily": series,
        "definitions": KPI_DEFINITIONS,
        "data_quality": {
            "insufficient_stage_semantics": insufficient_stage_semantics,
            "won_used_date_modify_fallback": won_missing_closedate,
            "note": (
                "Недостаточно данных по семантике этапов"
                if insufficient_stage_semantics
                else (
                    f"У {won_missing_closedate} won-сделок нет CLOSEDATE — использован date_modify"
                    if won_missing_closedate
                    else None
                )
            ),
        },
        "computed_at": now.isoformat(),
    }


async def _build_daily_series(
    session: AsyncSession,
    period_start: date,
    period_end: date,
    deal_filters: list[Any],
) -> list[dict[str, Any]]:
    """Daily new vs won counts for charts (Moscow calendar days)."""
    days = (period_end - period_start).days
    if days < 0:
        return []
    # Cap series length for limited resources
    if days > 92:
        period_start = period_end - timedelta(days=92)
        days = 92

    range_start, _ = local_day_bounds(period_start)
    _, range_end = local_day_bounds(period_end)

    new_rows = (
        await session.execute(
            select(CrmDeal.date_create).where(
                CrmDeal.date_create >= range_start,
                CrmDeal.date_create <= range_end,
                *deal_filters,
            )
        )
    ).all()
    won_rows = (
        await session.execute(
            select(CrmDeal.closedate, CrmDeal.date_modify)
            .join(CrmStage, CrmDeal.stage_id == CrmStage.id, isouter=True)
            .where(
                CrmDeal.closed.is_(True),
                CrmStage.semantics == "success",
                *deal_filters,
            )
        )
    ).all()

    new_by_day: dict[str, int] = {}
    for (created,) in new_rows:
        ts = _as_utc(created)
        if not ts:
            continue
        local_d = ts.astimezone(app_tz()).date()
        if period_start <= local_d <= period_end:
            key = local_d.isoformat()
            new_by_day[key] = new_by_day.get(key, 0) + 1

    won_by_day: dict[str, int] = {}
    for closedate, date_modify in won_rows:
        ts = _as_utc(closedate or date_modify)
        if not ts:
            continue
        local_d = ts.astimezone(app_tz()).date()
        if period_start <= local_d <= period_end:
            key = local_d.isoformat()
            won_by_day[key] = won_by_day.get(key, 0) + 1

    series: list[dict[str, Any]] = []
    for i in range(days + 1):
        d = period_start + timedelta(days=i)
        key = d.isoformat()
        series.append({"date": key, "new": new_by_day.get(key, 0), "won": won_by_day.get(key, 0)})
    return series


async def compute_manager_stats(
    session: AsyncSession,
    manager_id: int,
    period_start: date,
    period_end: date,
) -> dict[str, Any]:
    kpis = await compute_period_kpis(
        session, period_start, period_end, manager_id=manager_id
    )
    deals = (
        await session.execute(
            select(CrmDeal)
            .where(CrmDeal.assigned_by_id == manager_id)
            .options(selectinload(CrmDeal.stage))
            .order_by(CrmDeal.date_modify.desc().nullslast())
            .limit(100)
        )
    ).scalars().all()
    return {
        "kpis": kpis,
        "deals": [
            {
                "id": d.id,
                "bitrix_id": d.bitrix_id,
                "title": d.title,
                "closed": d.closed,
                "opportunity": float(d.opportunity) if d.opportunity is not None else None,
                "stage_name": d.stage.name if d.stage else None,
                "has_future_activity": d.has_future_activity,
                "date_modify": d.date_modify.isoformat() if d.date_modify else None,
            }
            for d in deals
        ],
    }

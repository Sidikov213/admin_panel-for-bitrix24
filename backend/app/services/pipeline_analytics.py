"""Pipeline funnel: current distribution vs period outcomes (no fake conversion history)."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analytics.kpi import compute_period_kpis
from app.core.timezone import local_day_bounds
from app.models.crm import CrmDeal, CrmPipeline, CrmStage, DealChangeEvent


async def pipeline_analytics(
    session: AsyncSession,
    *,
    period_start: date,
    period_end: date,
) -> dict[str, Any]:
    pipes = (
        await session.execute(
            select(CrmPipeline).options(selectinload(CrmPipeline.stages)).order_by(CrmPipeline.sort)
        )
    ).scalars().all()

    # Active totals for share calculation
    active_total = (
        await session.execute(
            select(func.count()).select_from(CrmDeal).where(
                CrmDeal.closed.is_(False), CrmDeal.missing_from_bitrix.is_(False)
            )
        )
    ).scalar_one()

    start_utc, _ = local_day_bounds(period_start)
    _, end_utc = local_day_bounds(period_end)

    result_pipes: list[dict[str, Any]] = []
    for p in pipes:
        stages_sorted = sorted(p.stages, key=lambda s: s.sort)
        stage_ids = [s.id for s in stages_sorted]

        # Current distribution (snapshot now)
        stage_rows = []
        if stage_ids:
            agg = (
                await session.execute(
                    select(
                        CrmDeal.stage_id,
                        func.count(CrmDeal.id),
                        func.coalesce(func.sum(CrmDeal.opportunity), 0),
                    )
                    .where(
                        CrmDeal.closed.is_(False),
                        CrmDeal.missing_from_bitrix.is_(False),
                        CrmDeal.category_id == p.bitrix_id,
                        CrmDeal.stage_id.in_(stage_ids),
                    )
                    .group_by(CrmDeal.stage_id)
                )
            ).all()
            by_stage = {sid: (cnt, float(amt)) for sid, cnt, amt in agg}
        else:
            by_stage = {}

        active_in_pipe = sum(v[0] for v in by_stage.values())
        amount_in_pipe = sum(v[1] for v in by_stage.values())

        for s in stages_sorted:
            cnt, amt = by_stage.get(s.id, (0, 0.0))
            stage_rows.append(
                {
                    "stage_id": s.id,
                    "bitrix_id": s.bitrix_id,
                    "name": s.name,
                    "sort": s.sort,
                    "semantics": s.semantics,
                    "deals_count": cnt,
                    "amount": amt,
                    "share_of_active_pipeline": (
                        round(cnt / active_in_pipe * 100.0, 1) if active_in_pipe else 0.0
                    ),
                    "share_of_all_active": (
                        round(cnt / active_total * 100.0, 1) if active_total else 0.0
                    ),
                }
            )

        # Period outcomes for this Bitrix category
        kpis = await compute_period_kpis(
            session, period_start, period_end, pipeline_id=p.bitrix_id, include_series=False
        )

        # Observed stage advances in period (change events) — not full conversion history
        advances = 0
        if stage_ids:
            advances = (
                await session.execute(
                    select(func.count())
                    .select_from(DealChangeEvent)
                    .join(CrmDeal, CrmDeal.id == DealChangeEvent.deal_id)
                    .where(
                        DealChangeEvent.field_name == "stage_id",
                        DealChangeEvent.observed_at >= start_utc,
                        DealChangeEvent.observed_at <= end_utc,
                        CrmDeal.category_id == p.bitrix_id,
                    )
                )
            ).scalar_one()

        result_pipes.append(
            {
                "id": p.id,
                "bitrix_id": p.bitrix_id,
                "name": p.name,
                "current_distribution": {
                    "active_deals": active_in_pipe,
                    "active_amount": amount_in_pipe,
                    "share_of_all_active": (
                        round(active_in_pipe / active_total * 100.0, 1) if active_total else 0.0
                    ),
                    "stages": stage_rows,
                    "note": "Текущее распределение активных сделок (снимок), не историческая конверсия",
                },
                "period_outcomes": {
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "new_deals": kpis["new_deals_count"],
                    "won": kpis["won_count"],
                    "lost": kpis["lost_count"],
                    "sum_won": kpis["sum_won_opportunity"],
                    "observed_stage_changes": int(advances or 0),
                    "note": (
                        "Исходы за период и наблюдаемые смены этапов. "
                        "Полная conversion history не строится при недостатке данных."
                    ),
                },
                "funnel": [
                    {"name": s["name"], "value": s["deals_count"], "amount": s["amount"]}
                    for s in stage_rows
                    if s["semantics"] not in ("success", "failure") or s["deals_count"] > 0
                ],
            }
        )

    return {
        "pipelines": result_pipes,
        "all_active_deals": int(active_total or 0),
        "distinction": {
            "current_distribution": "Сколько сделок сейчас на каждом этапе",
            "historical_conversion": "Не рассчитывается полностью — недостаточно непрерывной истории этапов",
        },
    }

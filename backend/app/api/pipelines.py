from datetime import date

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.analytics.periods import resolve_period
from app.auth.deps import CurrentUser, DbSession
from app.models.crm import CrmPipeline
from app.services.pipeline_analytics import pipeline_analytics

router = APIRouter()


@router.get("")
async def list_pipelines(
    _user: CurrentUser,
    db: DbSession,
    period_start: date | None = Query(default=None),
    period_end: date | None = Query(default=None),
    preset: str | None = Query(default=None),
    analytics: bool = Query(default=True),
) -> dict | list[dict]:
    if not analytics:
        stmt = select(CrmPipeline).options(selectinload(CrmPipeline.stages)).order_by(CrmPipeline.sort)
        pipes = (await db.execute(stmt)).scalars().all()
        return [
            {
                "id": p.id,
                "bitrix_id": p.bitrix_id,
                "name": p.name,
                "sort": p.sort,
                "stages": [
                    {
                        "id": s.id,
                        "bitrix_id": s.bitrix_id,
                        "name": s.name,
                        "sort": s.sort,
                        "semantics": s.semantics,
                    }
                    for s in p.stages
                ],
            }
            for p in pipes
        ]

    rng = resolve_period(preset=preset, period_start=period_start, period_end=period_end)
    data = await pipeline_analytics(db, period_start=rng.start, period_end=rng.end)
    data["period"] = {"start": rng.start.isoformat(), "end": rng.end.isoformat(), "preset": rng.preset}
    return data

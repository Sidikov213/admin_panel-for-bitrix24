from datetime import date

from fastapi import APIRouter, Query

from app.analytics.kpi import compute_period_kpis
from app.auth.deps import CurrentUser, DbSession

router = APIRouter()


@router.get("")
async def reports(
    _user: CurrentUser,
    db: DbSession,
    period_start: date = Query(...),
    period_end: date = Query(...),
    pipeline_id: int | None = None,
    manager_id: int | None = None,
) -> dict:
    metrics = await compute_period_kpis(db, period_start, period_end, pipeline_id, manager_id)
    return {"report": metrics}

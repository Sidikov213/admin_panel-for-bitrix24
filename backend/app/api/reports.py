from datetime import date

from fastapi import APIRouter, Query

from app.analytics.kpi import compute_period_kpis
from app.auth.deps import CurrentUser, DbSession
from app.services.reports_service import ReportsService

router = APIRouter()


@router.get("")
async def reports(
    _user: CurrentUser,
    db: DbSession,
    period_start: date | None = Query(default=None),
    period_end: date | None = Query(default=None),
    preset: str | None = Query(default="current_week"),
    pipeline_id: int | None = None,
    manager_id: int | None = None,
    legacy: bool = Query(default=False, description="Return raw KPI only"),
) -> dict:
    if legacy and period_start and period_end:
        metrics = await compute_period_kpis(db, period_start, period_end, pipeline_id, manager_id)
        return {"report": metrics}
    return await ReportsService(db).weekly_report(
        preset=preset, period_start=period_start, period_end=period_end
    )

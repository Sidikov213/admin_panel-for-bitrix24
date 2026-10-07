from datetime import date

from fastapi import APIRouter, Query

from app.auth.deps import CurrentUser, DbSession
from app.services.dashboard_service import DashboardService

router = APIRouter()


@router.get("/dashboard")
async def dashboard(
    _user: CurrentUser,
    db: DbSession,
    period_start: date | None = Query(default=None),
    period_end: date | None = Query(default=None),
    pipeline_id: int | None = Query(default=None),
    manager_id: int | None = Query(default=None),
) -> dict:
    return await DashboardService(db).get_dashboard(
        period_start=period_start,
        period_end=period_end,
        pipeline_id=pipeline_id,
        manager_id=manager_id,
    )

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.analytics.funnel import compute_funnel
from app.auth.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.timezone import app_tz, utc_now
from app.models.crm import CrmPipeline
from app.services.dashboard_service import DashboardService

router = APIRouter()

# Funnel needs a longer default window than the dashboard: deals take weeks to close
FUNNEL_DEFAULT_DAYS = 90
FUNNEL_MAX_DAYS = 731


@router.get("/funnel")
async def funnel(
    _user: CurrentUser,
    db: DbSession,
    category_id: int | None = Query(default=None, description="Bitrix CATEGORY_ID воронки"),
    period_start: date | None = Query(default=None),
    period_end: date | None = Query(default=None),
    manager_id: int | None = Query(default=None),
) -> dict:
    end = period_end or utc_now().astimezone(app_tz()).date()
    start = period_start or end - timedelta(days=FUNNEL_DEFAULT_DAYS - 1)
    if start > end:
        raise HTTPException(status_code=422, detail="Начало периода позже конца")
    if (end - start).days + 1 > FUNNEL_MAX_DAYS:
        raise HTTPException(status_code=422, detail="Период не может быть длиннее двух лет")
    if category_id is None:
        configured = get_settings().bitrix_category_ids
        pipe = (
            await db.execute(
                select(CrmPipeline).where(CrmPipeline.bitrix_id.in_(configured)).order_by(CrmPipeline.sort, CrmPipeline.id)
            )
        ).scalars().first()
        if pipe is None:
            pipe = (await db.execute(select(CrmPipeline).order_by(CrmPipeline.sort, CrmPipeline.id))).scalars().first()
        if pipe is None:
            raise HTTPException(status_code=404, detail="Воронки ещё не синхронизированы")
        category_id = pipe.bitrix_id
    return await compute_funnel(
        db, category_id=category_id, period_start=start, period_end=end, manager_id=manager_id
    )


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

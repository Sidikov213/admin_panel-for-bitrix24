from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query

from app.analytics.overdue import overdue_report
from app.auth.deps import CurrentUser, DbSession
from app.core.timezone import app_tz, utc_now

router = APIRouter()

PERIODS = ("today", "yesterday", "week", "month")


def period_bounds(period: str | None, date_from: date | None, date_to: date | None) -> tuple[date, date]:
    today = utc_now().astimezone(app_tz()).date()
    if date_from or date_to:
        start, end = date_from or date_to, date_to or date_from
    elif period == "today":
        start = end = today
    elif period == "yesterday":
        start = end = today - timedelta(days=1)
    elif period == "week":
        start, end = today - timedelta(days=6), today
    else:  # month (default)
        start, end = today - timedelta(days=29), today
    if start > end:  # type: ignore[operator]
        raise HTTPException(status_code=422, detail="Начало периода позже конца")
    if (end - start).days > 366:  # type: ignore[operator]
        raise HTTPException(status_code=422, detail="Период не может быть длиннее года")
    return start, end  # type: ignore[return-value]


@router.get("")
async def list_overdue(
    _user: CurrentUser,
    db: DbSession,
    period: str | None = Query(default="month", pattern="^(today|yesterday|week|month)$"),
    date_from: date | None = None,
    date_to: date | None = None,
    manager_id: int | None = None,
    category_id: int | None = None,
    stage_id: int | None = None,
    only_open: bool = False,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Activities with a deadline in the period that was missed (open now or closed late)."""
    start, end = period_bounds(period, date_from, date_to)
    return await overdue_report(
        db,
        date_from=start,
        date_to=end,
        manager_id=manager_id,
        category_id=category_id,
        stage_id=stage_id,
        only_open=only_open,
        offset=offset,
        limit=limit,
    )

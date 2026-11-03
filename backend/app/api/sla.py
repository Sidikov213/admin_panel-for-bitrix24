from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.analytics.sla import UNITS, load_rules, reaction_stats, stuck_deals
from app.auth.csrf import validate_csrf
from app.auth.deps import AdminUser, CurrentUser, DbSession
from app.core.timezone import app_tz, utc_now
from app.core.work_calendar import get_work_calendar
from app.models.crm import StageSlaRule

router = APIRouter()


class RuleIn(BaseModel):
    # null = do not track this stage
    threshold: Decimal | None = Field(default=None, gt=0, le=1000, max_digits=10, decimal_places=2)
    unit: str = Field(pattern="^(" + "|".join(UNITS) + ")$")
    reaction_stage: bool = False


@router.get("/rules")
async def list_rules(_user: CurrentUser, db: DbSession) -> dict:
    cal = get_work_calendar()
    rules = await load_rules(db)
    return {
        "items": [r.to_dict() for r in rules.values()],
        "units": {"work_hours": "рабочих часов", "work_days": "рабочих дней", "calendar_days": "календарных дней"},
        "work_calendar": {
            "hours": f"{cal.start:%H:%M}–{cal.end:%H:%M}",
            "workdays": sorted(cal.workdays),
            "holidays": [f"{a[1]:02d}.{a[0]:02d}–{b[1]:02d}.{b[0]:02d}" for a, b in cal.holidays],
        },
    }


@router.put("/rules/{stage_bitrix_id}")
async def put_rule(
    stage_bitrix_id: str,
    body: RuleIn,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    validate_csrf(request, csrf_header)
    rules = await load_rules(db)
    if stage_bitrix_id not in rules:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Стадия не найдена")
    row = (
        await db.execute(select(StageSlaRule).where(StageSlaRule.stage_bitrix_id == stage_bitrix_id))
    ).scalar_one_or_none()
    if row is None:
        row = StageSlaRule(stage_bitrix_id=stage_bitrix_id)
        db.add(row)
    row.threshold, row.unit, row.reaction_stage = body.threshold, body.unit, body.reaction_stage
    await db.flush()
    return (await load_rules(db))[stage_bitrix_id].to_dict()


@router.delete("/rules/{stage_bitrix_id}")
async def reset_rule(
    stage_bitrix_id: str,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    """Back to the default deadline for this stage."""
    validate_csrf(request, csrf_header)
    row = (
        await db.execute(select(StageSlaRule).where(StageSlaRule.stage_bitrix_id == stage_bitrix_id))
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.flush()
    rules = await load_rules(db)
    if stage_bitrix_id not in rules:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Стадия не найдена")
    return rules[stage_bitrix_id].to_dict()


@router.get("/stuck")
async def list_stuck(
    _user: CurrentUser,
    db: DbSession,
    category_id: int | None = None,
    manager_id: int | None = None,
    only_stuck: bool = True,
) -> dict:
    return await stuck_deals(db, category_id=category_id, manager_id=manager_id, only_stuck=only_stuck)


@router.get("/reaction")
async def reaction(
    _user: CurrentUser,
    db: DbSession,
    period_start: date | None = None,
    period_end: date | None = None,
    category_id: int | None = None,
    manager_id: int | None = None,
) -> dict:
    end = period_end or utc_now().astimezone(app_tz()).date()
    start = period_start or end - timedelta(days=29)
    if start > end:
        raise HTTPException(status_code=422, detail="Начало периода позже конца")
    if (end - start).days > 366:
        raise HTTPException(status_code=422, detail="Период не может быть длиннее года")
    return await reaction_stats(
        db, period_start=start, period_end=end, category_id=category_id, manager_id=manager_id
    )

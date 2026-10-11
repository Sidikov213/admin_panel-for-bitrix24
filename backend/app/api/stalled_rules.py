"""Admin API for configurable stalled rules — no default thresholds applied."""

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.csrf import validate_csrf
from app.auth.deps import AdminUser, CurrentUser, DbSession
from app.models.stalled_rules import StalledRule
from app.schemas.common import ORMModel

router = APIRouter()


class StalledRuleOut(ORMModel):
    id: int
    pipeline_bitrix_id: int | None
    stage_id: int | None
    max_idle_minutes: int | None
    future_activity_required: bool
    max_next_activity_minutes: int | None
    deal_status: str
    use_business_calendar: bool
    enabled: bool
    name: str
    note: str | None


class StalledRuleCreate(BaseModel):
    pipeline_bitrix_id: int | None = None
    stage_id: int | None = None
    max_idle_minutes: int | None = Field(default=None, ge=1)
    future_activity_required: bool = True
    max_next_activity_minutes: int | None = Field(default=None, ge=1)
    deal_status: str = "open"
    use_business_calendar: bool = False
    enabled: bool = False
    name: str = ""
    note: str | None = None


class StalledRuleUpdate(BaseModel):
    pipeline_bitrix_id: int | None = None
    stage_id: int | None = None
    max_idle_minutes: int | None = Field(default=None, ge=1)
    future_activity_required: bool | None = None
    max_next_activity_minutes: int | None = Field(default=None, ge=1)
    deal_status: str | None = None
    use_business_calendar: bool | None = None
    enabled: bool | None = None
    name: str | None = None
    note: str | None = None


@router.get("")
async def list_rules(_user: CurrentUser, db: DbSession) -> dict:
    rows = (await db.execute(select(StalledRule).order_by(StalledRule.id))).scalars().all()
    return {
        "items": [StalledRuleOut.model_validate(r).model_dump() for r in rows],
        "total": len(rows),
        "engine_ready": True,
        "rules_applied": False,
        "note": (
            "Механизм правил готов. Значения порогов не заданы и не применяются "
            "до утверждения регламента отдела продаж. Пока показываются только объективные факты."
        ),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_rule(
    body: StalledRuleCreate,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    validate_csrf(request, csrf_header)
    # Force disabled until regulation approved — admin may store drafts
    row = StalledRule(**body.model_dump())
    if row.enabled:
        row.enabled = False
        row.note = (row.note or "") + " [auto-disabled until sales rules approved]"
    db.add(row)
    await db.flush()
    return StalledRuleOut.model_validate(row).model_dump()


@router.patch("/{rule_id}")
async def update_rule(
    rule_id: int,
    body: StalledRuleUpdate,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    validate_csrf(request, csrf_header)
    row = await db.get(StalledRule, rule_id)
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    data = body.model_dump(exclude_unset=True)
    # Refuse enabling until global flag — keep drafts only
    if data.get("enabled") is True:
        data["enabled"] = False
    for k, v in data.items():
        setattr(row, k, v)
    await db.flush()
    return StalledRuleOut.model_validate(row).model_dump()


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: int,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    validate_csrf(request, csrf_header)
    row = await db.get(StalledRule, rule_id)
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.delete(row)

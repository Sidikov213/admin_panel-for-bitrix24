from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.analytics.card_quality import (
    CHECK_LABELS,
    STANDARD_FIELD_LABELS,
    card_quality,
    load_quality_rules,
    validate_checks,
)
from app.auth.csrf import validate_csrf
from app.auth.deps import AdminUser, CurrentUser, DbSession
from app.models.crm import CardQualityRule

router = APIRouter()


class ChecksIn(BaseModel):
    checks: list[str] = Field(max_length=30)


@router.get("")
async def quality(
    _user: CurrentUser,
    db: DbSession,
    category_id: int | None = None,
    manager_id: int | None = None,
    check: str | None = None,
) -> dict:
    return await card_quality(db, category_id=category_id, manager_id=manager_id, check=check)


@router.get("/rules")
async def rules(_user: CurrentUser, db: DbSession) -> dict:
    items, fields = await load_quality_rules(db)
    return {
        "items": list(items.values()),
        "checks": CHECK_LABELS,
        # Fields an admin can require: standard ones + every user field of the portal
        "fields": [
            *({"code": c, "label": label} for c, label in STANDARD_FIELD_LABELS.items()),
            *(
                {"code": c, "label": meta.get("label") or c}
                for c, meta in sorted(fields.items(), key=lambda kv: str(kv[1].get("label", "")))
                if c.startswith("UF_")
            ),
        ],
    }


@router.put("/rules/{stage_bitrix_id}")
async def put_rule(
    stage_bitrix_id: str,
    body: ChecksIn,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    validate_csrf(request, csrf_header)
    items, fields = await load_quality_rules(db)
    if stage_bitrix_id not in items:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Стадия не найдена")
    checks = list(dict.fromkeys(body.checks))
    try:
        validate_checks(checks, fields)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    row = (
        await db.execute(select(CardQualityRule).where(CardQualityRule.stage_bitrix_id == stage_bitrix_id))
    ).scalar_one_or_none()
    if row is None:
        row = CardQualityRule(stage_bitrix_id=stage_bitrix_id)
        db.add(row)
    row.checks = checks
    await db.flush()
    return (await load_quality_rules(db))[0][stage_bitrix_id]


@router.delete("/rules/{stage_bitrix_id}")
async def reset_rule(
    stage_bitrix_id: str,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    validate_csrf(request, csrf_header)
    row = (
        await db.execute(select(CardQualityRule).where(CardQualityRule.stage_bitrix_id == stage_bitrix_id))
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.flush()
    items, _ = await load_quality_rules(db)
    if stage_bitrix_id not in items:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Стадия не найдена")
    return items[stage_bitrix_id]

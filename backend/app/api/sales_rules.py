"""Admin + read APIs for sales rules engine."""

from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.csrf import validate_csrf
from app.auth.deps import AdminUser, CurrentUser, DbSession
from app.models.sales_rules import SalesRuleAudit, ViolationStatus
from app.models.sales_rules import SalesRuleViolation
from app.services.sales_rules import aggregates, crud
from app.services.sales_rules.engine import preview_rule_impact, run_evaluation
from app.services.sales_rules.fields_meta import list_deal_fields, sync_deal_fields
from app.services.sales_rules.humanize import describe_rule

router = APIRouter()


class SalesRuleBody(BaseModel):
    rule_name: str = ""
    description: str | None = None
    pipeline_bitrix_id: int | None = None
    stage_id: int | None = None
    enabled: bool = False
    max_idle_minutes: int | None = Field(default=None, ge=1)
    future_activity_required: bool | None = None
    max_next_activity_minutes: int | None = Field(default=None, ge=1)
    overdue_activity_allowed: bool | None = None
    required_fields: list[str] | None = None
    required_comment: bool | None = None
    comment_max_age_minutes: int | None = Field(default=None, ge=1)
    max_stage_duration_minutes: int | None = Field(default=None, ge=1)
    severity: str = "medium"


class SalesRuleUpdate(BaseModel):
    rule_name: str | None = None
    description: str | None = None
    pipeline_bitrix_id: int | None = None
    stage_id: int | None = None
    enabled: bool | None = None
    max_idle_minutes: int | None = Field(default=None, ge=1)
    future_activity_required: bool | None = None
    max_next_activity_minutes: int | None = Field(default=None, ge=1)
    overdue_activity_allowed: bool | None = None
    required_fields: list[str] | None = None
    required_comment: bool | None = None
    comment_max_age_minutes: int | None = Field(default=None, ge=1)
    max_stage_duration_minutes: int | None = Field(default=None, ge=1)
    severity: str | None = None


@router.get("")
async def list_sales_rules(_user: CurrentUser, db: DbSession) -> dict:
    rows = await crud.list_rules(db)
    items = [await crud.rule_with_description(db, r) for r in rows]
    return {
        "items": items,
        "total": len(items),
        "enabled_count": sum(1 for i in items if i["enabled"]),
        "comments_capability": "unsupported",
        "comments_note": (
            "Проверка комментариев недоступна: синхронизация ленты и комментариев Bitrix "
            "пока не подключена. Настройки «обязательный комментарий» и «срок комментария» "
            "сохранены, но ещё не применяются."
        ),
    }


@router.get("/deal-fields")
async def get_deal_fields(_user: CurrentUser, db: DbSession) -> dict:
    fields = await list_deal_fields(db)
    return {"items": fields, "total": len(fields)}


@router.post("/deal-fields/sync", status_code=status.HTTP_200_OK)
async def sync_fields(
    admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    validate_csrf(request, csrf_header)
    return await sync_deal_fields(db)


@router.post("/preview")
async def preview_rule(
    body: SalesRuleBody,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    validate_csrf(request, csrf_header)
    payload = body.model_dump()
    impact = await preview_rule_impact(db, payload)
    impact["human_description"] = describe_rule(payload)
    return impact


@router.post("/evaluate", status_code=status.HTTP_200_OK)
async def trigger_evaluation(
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    """Manual local analytics job — does not touch Bitrix."""
    validate_csrf(request, csrf_header)
    return await run_evaluation(db)


@router.get("/violations")
async def list_violations(
    _user: CurrentUser,
    db: DbSession,
    status_filter: str | None = Query(default="open", alias="status"),
    manager_id: int | None = None,
    deal_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    stmt = select(SalesRuleViolation).order_by(SalesRuleViolation.detected_at.desc()).limit(limit)
    if status_filter:
        stmt = stmt.where(SalesRuleViolation.status == status_filter)
    if manager_id is not None:
        stmt = stmt.where(SalesRuleViolation.manager_id == manager_id)
    if deal_id is not None:
        stmt = stmt.where(SalesRuleViolation.deal_id == deal_id)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": v.id,
                "deal_id": v.deal_id,
                "rule_id": v.rule_id,
                "type": v.violation_type,
                "severity": v.severity,
                "status": v.status,
                "details": v.details,
                "current_value": v.current_value,
                "threshold": v.threshold,
                "detected_at": v.detected_at.isoformat() if v.detected_at else None,
                "resolved_at": v.resolved_at.isoformat() if v.resolved_at else None,
                "manager_id": v.manager_id,
            }
            for v in rows
        ],
        "total": len(rows),
    }


@router.get("/audits")
async def list_audits(_admin: AdminUser, db: DbSession, limit: int = Query(default=50, ge=1, le=200)) -> dict:
    rows = (
        await db.execute(select(SalesRuleAudit).order_by(SalesRuleAudit.created_at.desc()).limit(limit))
    ).scalars().all()
    return {
        "items": [
            {
                "id": a.id,
                "rule_id": a.rule_id,
                "user_id": a.user_id,
                "user_email": a.user_email,
                "action": a.action,
                "before": a.before,
                "after": a.after,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows
        ]
    }


@router.get("/{rule_id}")
async def get_sales_rule(rule_id: int, _user: CurrentUser, db: DbSession) -> dict:
    row = await crud.get_rule(db, rule_id)
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    return await crud.rule_with_description(db, row)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_sales_rule(
    body: SalesRuleBody,
    admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    validate_csrf(request, csrf_header)
    rule = await crud.create_rule(
        db,
        body.model_dump(),
        user_id=admin.id,
        user_email=admin.email,
    )
    return await crud.rule_with_description(db, rule)


@router.patch("/{rule_id}")
async def update_sales_rule(
    rule_id: int,
    body: SalesRuleUpdate,
    admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    validate_csrf(request, csrf_header)
    row = await crud.get_rule(db, rule_id)
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    await crud.update_rule(
        db,
        row,
        body.model_dump(exclude_unset=True),
        user_id=admin.id,
        user_email=admin.email,
    )
    return await crud.rule_with_description(db, row)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sales_rule(
    rule_id: int,
    admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    validate_csrf(request, csrf_header)
    row = await crud.get_rule(db, rule_id)
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    await crud.delete_rule(db, row, user_id=admin.id, user_email=admin.email)

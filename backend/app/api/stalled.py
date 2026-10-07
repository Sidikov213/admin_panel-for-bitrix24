from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.auth.deps import CurrentUser, DbSession
from app.core.timezone import utc_now
from app.models.crm import CrmDeal
from app.services.stalled_rules import RULES_ENABLED, StalledRulesConfig, is_stalled

router = APIRouter()


@router.get("")
async def list_stalled(
    _user: CurrentUser,
    db: DbSession,
    mode: str = Query(
        default="no_future",
        description="no_future | rules — факт без следующего дела или настраиваемые правила",
    ),
) -> dict:
    cfg = StalledRulesConfig()

    if mode == "rules" and not RULES_ENABLED:
        return {
            "mode": "rules",
            "enabled": False,
            "items": [],
            "total": 0,
            "rules_config": {
                "min_hours_since_last_activity": None,
                "min_hours_since_stage_change": None,
                "require_no_future_activity": None,
                "note": (
                    "Регламент отдела продаж ещё не утверждён. "
                    "Предварительные пороги не применяются как бизнес-норматив."
                ),
            },
            "disclaimer": "Правила отключены до утверждения регламента.",
        }

    deals = (
        await db.execute(
            select(CrmDeal)
            .where(CrmDeal.closed.is_(False))
            .options(selectinload(CrmDeal.stage), selectinload(CrmDeal.assigned_manager))
        )
    ).scalars().all()
    items = []
    now = utc_now()
    for d in deals:
        stalled, reason = is_stalled(
            last_observed_activity_at=d.last_observed_activity_at,
            stage_changed_observed_at=d.stage_changed_observed_at,
            has_future_activity=d.has_future_activity,
            closed=d.closed,
            config=cfg,
        )
        no_future = not d.has_future_activity
        if mode == "rules" and not stalled:
            continue
        if mode == "no_future" and not no_future:
            continue
        if mode not in ("rules", "no_future") and not (stalled or no_future):
            continue

        ref = d.last_observed_activity_at or d.stage_changed_observed_at or d.date_modify
        hours = round((now - ref).total_seconds() / 3600, 1) if ref else None
        items.append(
            {
                "deal_id": d.id,
                "bitrix_id": d.bitrix_id,
                "title": d.title,
                "reason": reason if mode == "rules" else None,
                "last_observed_activity_at": (
                    d.last_observed_activity_at.isoformat() if d.last_observed_activity_at else None
                ),
                "stage_changed_observed_at": (
                    d.stage_changed_observed_at.isoformat() if d.stage_changed_observed_at else None
                ),
                "has_future_activity": d.has_future_activity,
                "no_future_activity": no_future,
                "label_no_future": "нет следующего запланированного дела" if no_future else None,
                "hours_without_observed_movement": hours,
                "stage": d.stage.name if d.stage else None,
                "manager": (
                    f"{d.assigned_manager.name} {d.assigned_manager.last_name}".strip()
                    if d.assigned_manager
                    else None
                ),
                "disclaimer": (
                    "Проверяемый факт по связанным делам, не нарушение SLA."
                    if mode == "no_future"
                    else "Правила предварительные, не утверждённый SLA компании."
                ),
            }
        )
    return {
        "mode": mode,
        "enabled": True,
        "items": items,
        "total": len(items),
        "rules_config": {
            "min_hours_since_last_activity": cfg.min_hours_since_last_activity if mode == "rules" else None,
            "min_hours_since_stage_change": cfg.min_hours_since_stage_change if mode == "rules" else None,
            "require_no_future_activity": cfg.require_no_future_activity if mode == "rules" else None,
            "note": (
                "Плейсхолдеры до утверждения регламента отдела продаж"
                if mode == "rules"
                else "Только факт отсутствия будущего дела"
            ),
        },
    }

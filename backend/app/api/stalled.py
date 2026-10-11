from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.analytics.attention import format_duration, no_future_summary
from app.auth.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.timezone import utc_now
from app.models.crm import CrmDeal
from app.models.stalled_rules import StalledRule
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
    manager_id: int | None = Query(default=None),
    pipeline_id: int | None = Query(default=None),
) -> dict:
    cfg = StalledRulesConfig()
    settings = get_settings()
    portal = (settings.BITRIX_PORTAL_URL or "").rstrip("/")

    enabled_rules = (
        await db.execute(select(func.count()).select_from(StalledRule).where(StalledRule.enabled.is_(True)))
    ).scalar_one()

    if mode == "rules" and (not RULES_ENABLED or int(enabled_rules or 0) == 0):
        return {
            "mode": "rules",
            "enabled": False,
            "items": [],
            "total": 0,
            "sum_opportunity": 0,
            "rules_config": {
                "note": (
                    "Регламент отдела продаж ещё не утверждён. "
                    "Правила можно подготовить в admin UI, но не применять как SLA."
                ),
            },
            "disclaimer": "Правила отключены до утверждения регламента.",
        }

    filters = [CrmDeal.closed.is_(False), CrmDeal.missing_from_bitrix.is_(False)]
    if mode == "no_future":
        filters.append(CrmDeal.has_future_activity.is_(False))
    if manager_id is not None:
        filters.append(CrmDeal.assigned_by_id == manager_id)
    if pipeline_id is not None:
        filters.append(CrmDeal.category_id == pipeline_id)

    deals = (
        await db.execute(
            select(CrmDeal)
            .where(*filters)
            .options(selectinload(CrmDeal.stage), selectinload(CrmDeal.assigned_manager))
            .order_by(CrmDeal.opportunity.desc().nullslast())
        )
    ).scalars().all()

    items = []
    now = utc_now()
    total_amount = 0.0
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

        ref = d.last_observed_activity_at or d.stage_changed_observed_at or d.date_modify
        idle_label = format_duration((now - ref).total_seconds()) if ref else None
        amt = float(d.opportunity) if d.opportunity is not None else 0.0
        total_amount += amt
        items.append(
            {
                "deal_id": d.id,
                "bitrix_id": d.bitrix_id,
                "title": d.title,
                "amount": float(d.opportunity) if d.opportunity is not None else None,
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
                "time_without_future_task": idle_label,
                "hours_without_observed_movement": (
                    round((now - ref).total_seconds() / 3600, 1) if ref else None
                ),
                "stage": d.stage.name if d.stage else None,
                "pipeline_category_id": d.category_id,
                "manager": (
                    f"{d.assigned_manager.name} {d.assigned_manager.last_name}".strip()
                    if d.assigned_manager
                    else None
                ),
                "manager_id": d.assigned_by_id,
                "bitrix_url": f"{portal}/crm/deal/details/{d.bitrix_id}/" if portal else None,
                "disclaimer": (
                    "Проверяемый факт по связанным делам, не нарушение SLA."
                    if mode == "no_future"
                    else "Правила предварительные, не утверждённый SLA компании."
                ),
            }
        )

    summary = await no_future_summary(db, pipeline_id=pipeline_id, manager_id=manager_id) if mode == "no_future" else None

    return {
        "mode": mode,
        "enabled": True,
        "items": items,
        "total": len(items),
        "sum_opportunity": summary["amount"] if summary else total_amount,
        "summary_label": (
            f"{summary['deals_count']} сделок · {summary['amount']:,.0f} ₽ без следующего действия".replace(",", " ")
            if summary
            else None
        ),
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

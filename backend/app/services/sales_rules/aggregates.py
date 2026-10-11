"""Violation aggregates for dashboard / managers / reports."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import local_day_bounds
from app.models.crm import CrmDeal, CrmManager
from app.models.sales_rules import SalesRule, SalesRuleViolation, ViolationStatus


async def rules_configured(session: AsyncSession) -> bool:
    n = (
        await session.execute(select(func.count()).select_from(SalesRule))
    ).scalar_one()
    return int(n or 0) > 0


async def enabled_rules_count(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).select_from(SalesRule).where(SalesRule.enabled.is_(True))
            )
        ).scalar_one()
        or 0
    )


async def dashboard_violation_kpis(session: AsyncSession) -> dict[str, Any]:
    if not await enabled_rules_count(session):
        return {
            "rules_configured": await rules_configured(session),
            "enabled_rules": 0,
            "deals_with_violations": 0,
            "high_severity_violations": 0,
            "amount_under_violations": 0.0,
            "open_violations": 0,
            "note": "Регламент не настроен" if not await rules_configured(session) else "Правила выключены",
        }

    open_q = select(SalesRuleViolation).where(SalesRuleViolation.status == ViolationStatus.open.value)
    open_count = (
        await session.execute(select(func.count()).select_from(open_q.subquery()))
    ).scalar_one()

    high = (
        await session.execute(
            select(func.count())
            .select_from(SalesRuleViolation)
            .where(
                SalesRuleViolation.status == ViolationStatus.open.value,
                SalesRuleViolation.severity.in_(("high", "critical")),
            )
        )
    ).scalar_one()

    # Deduped deal amount under any open violation
    deal_ids_sq = (
        select(SalesRuleViolation.deal_id)
        .where(SalesRuleViolation.status == ViolationStatus.open.value)
        .distinct()
        .subquery()
    )
    deals_with = (
        await session.execute(select(func.count()).select_from(deal_ids_sq))
    ).scalar_one()
    amount_row = (
        await session.execute(
            select(func.coalesce(func.sum(CrmDeal.opportunity), 0)).where(
                CrmDeal.id.in_(select(deal_ids_sq.c.deal_id))
            )
        )
    ).scalar_one()

    return {
        "rules_configured": True,
        "enabled_rules": await enabled_rules_count(session),
        "deals_with_violations": int(deals_with or 0),
        "high_severity_violations": int(high or 0),
        "amount_under_violations": float(amount_row or 0),
        "open_violations": int(open_count or 0),
        "note": None,
    }


async def manager_violation_stats(
    session: AsyncSession,
    *,
    manager_id: int | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> dict[int, dict[str, Any]]:
    """Per-manager open / high / resolved / rate. Rate = open_violations / active_deals."""
    # Active deals per manager
    active_filters = [CrmDeal.closed.is_(False), CrmDeal.missing_from_bitrix.is_(False)]
    if manager_id is not None:
        active_filters.append(CrmDeal.assigned_by_id == manager_id)
    active_rows = (
        await session.execute(
            select(CrmDeal.assigned_by_id, func.count(CrmDeal.id)).where(*active_filters).group_by(CrmDeal.assigned_by_id)
        )
    ).all()
    active_map = {r[0]: int(r[1]) for r in active_rows}

    open_filters = [SalesRuleViolation.status == ViolationStatus.open.value]
    if manager_id is not None:
        open_filters.append(SalesRuleViolation.manager_id == manager_id)
    open_rows = (
        await session.execute(
            select(
                SalesRuleViolation.manager_id,
                func.count(SalesRuleViolation.id),
                func.sum(
                    case(
                        (SalesRuleViolation.severity.in_(("high", "critical")), 1),
                        else_=0,
                    )
                ),
            )
            .where(*open_filters)
            .group_by(SalesRuleViolation.manager_id)
        )
    ).all()

    resolved_filters = [SalesRuleViolation.status == ViolationStatus.resolved.value]
    if manager_id is not None:
        resolved_filters.append(SalesRuleViolation.manager_id == manager_id)
    if period_start and period_end:
        start_utc, _ = local_day_bounds(period_start)
        _, end_utc = local_day_bounds(period_end)
        resolved_filters.append(SalesRuleViolation.resolved_at >= start_utc)
        resolved_filters.append(SalesRuleViolation.resolved_at <= end_utc)
    resolved_rows = (
        await session.execute(
            select(SalesRuleViolation.manager_id, func.count(SalesRuleViolation.id))
            .where(*resolved_filters)
            .group_by(SalesRuleViolation.manager_id)
        )
    ).all()
    resolved_map = {r[0]: int(r[1]) for r in resolved_rows}

    out: dict[int, dict[str, Any]] = {}
    manager_ids = set(active_map) | {r[0] for r in open_rows} | set(resolved_map)
    manager_ids.discard(None)
    for mid in manager_ids:
        if mid is None:
            continue
        open_c = 0
        high_c = 0
        for r in open_rows:
            if r[0] == mid:
                open_c = int(r[1] or 0)
                high_c = int(r[2] or 0)
        active = active_map.get(mid, 0)
        rate = round(open_c / active, 3) if active else None
        out[int(mid)] = {
            "manager_id": int(mid),
            "open_violations": open_c,
            "high_severity_violations": high_c,
            "resolved_violations": resolved_map.get(mid, 0),
            "active_deals": active,
            "violation_rate": rate,
        }
    return out


async def report_violations_block(
    session: AsyncSession,
    *,
    period_start: date,
    period_end: date,
) -> dict[str, Any]:
    if not await rules_configured(session):
        return {
            "label": "Нарушения регламента",
            "configured": False,
            "message": "Регламент не настроен",
        }
    if not await enabled_rules_count(session):
        return {
            "label": "Нарушения регламента",
            "configured": True,
            "enabled": False,
            "message": "Правила есть, но все выключены",
            "open": 0,
            "new_during_period": 0,
            "resolved": 0,
            "by_manager": [],
            "by_type": [],
        }

    start_utc, _ = local_day_bounds(period_start)
    _, end_utc = local_day_bounds(period_end)

    open_n = (
        await session.execute(
            select(func.count())
            .select_from(SalesRuleViolation)
            .where(SalesRuleViolation.status == ViolationStatus.open.value)
        )
    ).scalar_one()
    new_n = (
        await session.execute(
            select(func.count())
            .select_from(SalesRuleViolation)
            .where(
                SalesRuleViolation.detected_at >= start_utc,
                SalesRuleViolation.detected_at <= end_utc,
            )
        )
    ).scalar_one()
    resolved_n = (
        await session.execute(
            select(func.count())
            .select_from(SalesRuleViolation)
            .where(
                SalesRuleViolation.status == ViolationStatus.resolved.value,
                SalesRuleViolation.resolved_at >= start_utc,
                SalesRuleViolation.resolved_at <= end_utc,
            )
        )
    ).scalar_one()

    by_type = (
        await session.execute(
            select(SalesRuleViolation.violation_type, func.count())
            .where(SalesRuleViolation.status == ViolationStatus.open.value)
            .group_by(SalesRuleViolation.violation_type)
        )
    ).all()

    by_mgr = (
        await session.execute(
            select(
                SalesRuleViolation.manager_id,
                CrmManager.name,
                CrmManager.last_name,
                func.count(),
            )
            .outerjoin(CrmManager, CrmManager.id == SalesRuleViolation.manager_id)
            .where(SalesRuleViolation.status == ViolationStatus.open.value)
            .group_by(SalesRuleViolation.manager_id, CrmManager.name, CrmManager.last_name)
        )
    ).all()

    return {
        "label": "Нарушения регламента",
        "configured": True,
        "enabled": True,
        "open": int(open_n or 0),
        "new_during_period": int(new_n or 0),
        "resolved": int(resolved_n or 0),
        "by_type": [{"type": t, "count": int(c)} for t, c in by_type],
        "by_manager": [
            {
                "manager_id": mid,
                "manager_name": f"{(n or '')} {(ln or '')}".strip() or "Без менеджера",
                "count": int(c),
            }
            for mid, n, ln, c in by_mgr
        ],
    }


async def deal_violations(session: AsyncSession, deal_id: int) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(SalesRuleViolation, SalesRule)
            .join(SalesRule, SalesRule.id == SalesRuleViolation.rule_id)
            .where(SalesRuleViolation.deal_id == deal_id)
            .order_by(SalesRuleViolation.detected_at.desc())
        )
    ).all()
    active: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    for v, rule in rows:
        item = {
            "id": v.id,
            "rule_id": v.rule_id,
            "rule_name": rule.rule_name,
            "type": v.violation_type,
            "severity": v.severity,
            "status": v.status,
            "details": v.details,
            "current_value": v.current_value,
            "threshold": v.threshold,
            "detected_at": v.detected_at.isoformat() if v.detected_at else None,
            "resolved_at": v.resolved_at.isoformat() if v.resolved_at else None,
        }
        if v.status == ViolationStatus.open.value:
            active.append(item)
        else:
            resolved.append(item)
    return {"active": active, "resolved": resolved}


async def business_rule_attention(session: AsyncSession, *, limit: int = 40) -> dict[str, Any]:
    """Open business-rule violations for dashboard attention split."""
    if not await enabled_rules_count(session):
        return {
            "categories": {},
            "total": 0,
            "enabled_rules": 0,
            "note": "Регламент не настроен" if not await rules_configured(session) else "Правила выключены",
        }

    rows = (
        await session.execute(
            select(SalesRuleViolation, CrmDeal, SalesRule)
            .join(CrmDeal, CrmDeal.id == SalesRuleViolation.deal_id)
            .join(SalesRule, SalesRule.id == SalesRuleViolation.rule_id)
            .where(SalesRuleViolation.status == ViolationStatus.open.value)
            .options()
            .order_by(SalesRuleViolation.detected_at.desc())
            .limit(limit)
        )
    ).all()

    categories: dict[str, list[dict[str, Any]]] = {}
    for v, deal, rule in rows:
        cat = v.violation_type
        categories.setdefault(cat, []).append(
            {
                "deal_id": deal.id,
                "bitrix_id": deal.bitrix_id,
                "title": deal.title,
                "amount": float(deal.opportunity) if deal.opportunity is not None else None,
                "rule_id": rule.id,
                "rule_name": rule.rule_name,
                "severity": v.severity,
                "fact": v.details,
                "category": cat,
            }
        )
    return {
        "categories": {
            k: {"label": k, "count": len(v), "items": v} for k, v in categories.items()
        },
        "total": sum(len(v) for v in categories.values()),
        "enabled_rules": await enabled_rules_count(session),
        "note": None,
    }

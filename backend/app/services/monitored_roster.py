"""Monitored sales managers for Manager Control — not Bitrix ACTIVE flag."""

from __future__ import annotations

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.timezone import utc_now
from app.models.crm import CrmActivity, CrmDeal, CrmManager
from app.models.manager_control import MonitoredManager


async def discover_auto_manager_ids(session: AsyncSession) -> dict[int, str]:
    """Managers linked to synced-category deals as assignee or activity responsible."""
    settings = get_settings()
    categories = settings.bitrix_category_ids

    assigned = (
        await session.execute(
            select(distinct(CrmDeal.assigned_by_id)).where(
                CrmDeal.assigned_by_id.isnot(None),
                CrmDeal.missing_from_bitrix.is_(False),
                CrmDeal.category_id.in_(categories),
            )
        )
    ).scalars().all()
    reasons: dict[int, str] = {int(mid): "assigned_deals" for mid in assigned if mid is not None}

    # Activities on those deals by responsible bitrix id → manager
    deal_bitrix_ids = (
        await session.execute(
            select(CrmDeal.bitrix_id).where(
                CrmDeal.missing_from_bitrix.is_(False),
                CrmDeal.category_id.in_(categories),
            )
        )
    ).scalars().all()
    if deal_bitrix_ids:
        resp_bitrix = (
            await session.execute(
                select(distinct(CrmActivity.responsible_id)).where(
                    CrmActivity.responsible_id.isnot(None),
                    CrmActivity.owner_id.in_(list(deal_bitrix_ids)),
                    CrmActivity.owner_type_id == 2,
                )
            )
        ).scalars().all()
        if resp_bitrix:
            mgrs = (
                await session.execute(
                    select(CrmManager.id).where(CrmManager.bitrix_id.in_(list(resp_bitrix)))
                )
            ).scalars().all()
            for mid in mgrs:
                reasons.setdefault(int(mid), "activity_responsible")

    return reasons


async def sync_monitored_roster(session: AsyncSession) -> dict[str, int]:
    """Refresh auto_included flags; respect manual include/exclude."""
    auto = await discover_auto_manager_ids(session)
    existing = (
        await session.execute(select(MonitoredManager))
    ).scalars().all()
    by_id = {r.manager_id: r for r in existing}

    created = 0
    updated = 0
    for mid, reason in auto.items():
        row = by_id.get(mid)
        if row is None:
            session.add(
                MonitoredManager(
                    manager_id=mid,
                    auto_included=True,
                    manual_include=False,
                    manual_exclude=False,
                    auto_reason=reason,
                )
            )
            created += 1
        else:
            changed = False
            if not row.auto_included:
                row.auto_included = True
                changed = True
            if row.auto_reason != reason:
                row.auto_reason = reason
                changed = True
            if changed:
                updated += 1

    # Clear auto for managers no longer in CRM graph (keep manual rows)
    for mid, row in by_id.items():
        if mid not in auto and row.auto_included:
            row.auto_included = False
            row.auto_reason = None
            updated += 1
            if not row.manual_include and not row.manual_exclude:
                # orphan auto-only row — leave for history; still not monitored if neither flag
                pass

    await session.flush()
    return {"created": created, "updated": updated, "auto_count": len(auto)}


def is_monitored_row(row: MonitoredManager | None) -> bool:
    if row is None:
        return False
    if row.manual_exclude:
        return False
    return bool(row.manual_include or row.auto_included)


async def list_monitored_managers(session: AsyncSession) -> list[CrmManager]:
    """Managers currently monitored for board + collector."""
    await sync_monitored_roster(session)
    rows = (
        await session.execute(
            select(CrmManager, MonitoredManager)
            .join(MonitoredManager, MonitoredManager.manager_id == CrmManager.id)
            .where(
                MonitoredManager.manual_exclude.is_(False),
                or_(
                    MonitoredManager.manual_include.is_(True),
                    MonitoredManager.auto_included.is_(True),
                ),
            )
            .order_by(CrmManager.last_name.asc(), CrmManager.name.asc())
        )
    ).all()
    return [m for m, _ in rows]


async def set_manual_monitor(
    session: AsyncSession,
    manager_id: int,
    *,
    include: bool | None = None,
    exclude: bool | None = None,
    note: str | None = None,
) -> MonitoredManager:
    mgr = await session.get(CrmManager, manager_id)
    if mgr is None:
        raise ValueError("manager_not_found")
    row = await session.get(MonitoredManager, manager_id)
    if row is None:
        row = MonitoredManager(manager_id=manager_id, auto_included=False)
        session.add(row)
    if include is not None:
        row.manual_include = include
        if include:
            row.manual_exclude = False
    if exclude is not None:
        row.manual_exclude = exclude
        if exclude:
            row.manual_include = False
    if note is not None:
        row.note = note
    row.updated_at = utc_now()
    await session.flush()
    return row


async def list_roster_admin(session: AsyncSession) -> list[dict]:
    await sync_monitored_roster(session)
    rows = (
        await session.execute(
            select(CrmManager, MonitoredManager)
            .outerjoin(MonitoredManager, MonitoredManager.manager_id == CrmManager.id)
            .order_by(CrmManager.last_name.asc())
        )
    ).all()
    # Only show managers that are or could be relevant (have roster row or deals)
    out = []
    for mgr, mon in rows:
        if mon is None:
            continue
        out.append(
            {
                "manager_id": mgr.id,
                "bitrix_id": mgr.bitrix_id,
                "name": mgr.name,
                "last_name": mgr.last_name,
                "display_name": f"{mgr.name} {mgr.last_name}".strip(),
                "bitrix_user_active": mgr.is_active,
                "auto_included": mon.auto_included,
                "manual_include": mon.manual_include,
                "manual_exclude": mon.manual_exclude,
                "monitored": is_monitored_row(mon),
                "auto_reason": mon.auto_reason,
                "note": mon.note,
            }
        )
    return out

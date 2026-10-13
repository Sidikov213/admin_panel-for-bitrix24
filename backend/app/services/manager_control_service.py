"""Manager Control — current Timeman state + today metrics + CRM (monitored roster)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.timezone import app_tz, local_day_bounds, utc_now
from app.models.crm import CrmActivity, CrmDeal, CrmManager, DealChangeEvent
from app.models.manager_control import ManagerWorkday, ManagerWorkdaySnapshot
from app.models.work_schedules import WorkdayViolation
from app.repositories.sync import SyncRepository
from app.services.monitored_roster import list_monitored_managers
from app.services.schedule_service import get_or_create_policy, resolve_day_plan_for_manager
from app.services.timeman_collector import STATE_HISTORY_SINCE, STATE_LAST_SYNC
from app.services.timeman_parse import (
    STATUS_NO_DATA,
    STATUS_STALE_UNCLOSED,
    build_simple_timeline,
    classify_current_status,
    format_seconds,
    local_dates_back,
    status_label_ru,
)
from app.services.workday_rules import STATE_OPEN, violation_label_ru

FRESHNESS_STALE_MINUTES = 15


def _as_utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


async def get_timeman_freshness(session: AsyncSession) -> dict[str, Any]:
    repo = SyncRepository(session)
    state = await repo.get_state(STATE_LAST_SYNC) or {}
    hist = await repo.get_state(STATE_HISTORY_SINCE) or {}
    at_raw = state.get("at")
    last_at: datetime | None = None
    if at_raw:
        try:
            last_at = datetime.fromisoformat(str(at_raw))
        except ValueError:
            last_at = None
    age_minutes: float | None = None
    if last_at is not None:
        last_at = _as_utc(last_at)
        age_minutes = (utc_now() - last_at).total_seconds() / 60.0
    stale = age_minutes is None or age_minutes > FRESHNESS_STALE_MINUTES
    local_hhmm = None
    if last_at is not None:
        local_hhmm = last_at.astimezone(app_tz()).strftime("%H:%M")
    return {
        "last_updated_at": last_at.isoformat() if last_at else None,
        "last_updated_local": local_hhmm,
        "age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
        "stale": stale,
        "ok": bool(state.get("ok", False)) if state else False,
        "history_since": hist.get("local_date") or hist.get("at"),
        "history_since_note": (
            f"История рабочего времени собирается Focus Analytics с {hist.get('local_date') or 'запуска модуля'}"
            if hist
            else "История рабочего времени ещё не начата"
        ),
        "time_control": {
            "available": False,
            "label": "Расширенный контроль активности",
            "status": "Недоступно: контроль присутствия Time Control в Bitrix24 выключен.",
            "features": ["Простой", "Офлайн", "Активность за компьютером"],
        },
    }


async def _latest_snapshots(
    session: AsyncSession, manager_ids: list[int]
) -> dict[int, ManagerWorkdaySnapshot]:
    if not manager_ids:
        return {}
    # Distinct on manager_id ordered by observed_at desc — portable approach
    rows = (
        await session.execute(
            select(ManagerWorkdaySnapshot)
            .where(ManagerWorkdaySnapshot.manager_id.in_(manager_ids))
            .order_by(
                ManagerWorkdaySnapshot.manager_id.asc(),
                ManagerWorkdaySnapshot.observed_at.desc(),
            )
        )
    ).scalars().all()
    out: dict[int, ManagerWorkdaySnapshot] = {}
    for sn in rows:
        if sn.manager_id not in out:
            out[sn.manager_id] = sn
    return out


async def _crm_metrics_for_managers(
    session: AsyncSession,
    manager_ids: list[int],
    *,
    day: date,
) -> dict[int, dict[str, int]]:
    if not manager_ids:
        return {}
    start_utc, end_utc = local_day_bounds(day)
    now = utc_now()

    created = (
        await session.execute(
            select(CrmDeal.assigned_by_id, func.count())
            .where(
                CrmDeal.assigned_by_id.in_(manager_ids),
                CrmDeal.missing_from_bitrix.is_(False),
                CrmDeal.date_create >= start_utc,
                CrmDeal.date_create <= end_utc,
            )
            .group_by(CrmDeal.assigned_by_id)
        )
    ).all()
    created_map = {mid: int(c) for mid, c in created}

    change_rows = (
        await session.execute(
            select(
                CrmDeal.assigned_by_id,
                DealChangeEvent.field_name,
                func.count(),
            )
            .join(DealChangeEvent, DealChangeEvent.deal_id == CrmDeal.id)
            .where(
                CrmDeal.assigned_by_id.in_(manager_ids),
                DealChangeEvent.observed_at >= start_utc,
                DealChangeEvent.observed_at <= end_utc,
            )
            .group_by(CrmDeal.assigned_by_id, DealChangeEvent.field_name)
        )
    ).all()
    stage_changes: dict[int, int] = {}
    opportunity_changes: dict[int, int] = {}
    for mid, field, cnt in change_rows:
        n = int(cnt)
        if field == "stage_id":
            stage_changes[mid] = stage_changes.get(mid, 0) + n
        elif field == "opportunity":
            opportunity_changes[mid] = opportunity_changes.get(mid, 0) + n

    distinct_changed = (
        await session.execute(
            select(CrmDeal.assigned_by_id, func.count(func.distinct(CrmDeal.id)))
            .join(DealChangeEvent, DealChangeEvent.deal_id == CrmDeal.id)
            .where(
                CrmDeal.assigned_by_id.in_(manager_ids),
                DealChangeEvent.observed_at >= start_utc,
                DealChangeEvent.observed_at <= end_utc,
            )
            .group_by(CrmDeal.assigned_by_id)
        )
    ).all()
    changed_deal_count = {mid: int(c) for mid, c in distinct_changed}

    managers = (
        await session.execute(select(CrmManager).where(CrmManager.id.in_(manager_ids)))
    ).scalars().all()
    bitrix_to_id = {m.bitrix_id: m.id for m in managers}
    completed = (
        await session.execute(
            select(CrmActivity.responsible_id, func.count())
            .where(
                CrmActivity.responsible_id.in_(list(bitrix_to_id.keys()) or [-1]),
                CrmActivity.completed.is_(True),
                CrmActivity.completed_at.isnot(None),
                CrmActivity.completed_at >= start_utc,
                CrmActivity.completed_at <= end_utc,
            )
            .group_by(CrmActivity.responsible_id)
        )
    ).all()
    completed_map: dict[int, int] = {}
    for bid, cnt in completed:
        mid = bitrix_to_id.get(bid)
        if mid is not None:
            completed_map[mid] = int(cnt)

    overdue_rows = (
        await session.execute(
            select(CrmDeal.assigned_by_id, CrmActivity.bitrix_id)
            .join(CrmDeal, CrmDeal.bitrix_id == CrmActivity.owner_id)
            .where(
                CrmDeal.assigned_by_id.in_(manager_ids),
                CrmActivity.completed.is_(False),
                CrmActivity.deadline.isnot(None),
                CrmActivity.deadline < now,
                CrmDeal.missing_from_bitrix.is_(False),
            )
        )
    ).all()
    overdue_sets: dict[int, set[int]] = {}
    for mid, act_bid in overdue_rows:
        overdue_sets.setdefault(mid, set()).add(act_bid)

    no_future = (
        await session.execute(
            select(CrmDeal.assigned_by_id, func.count())
            .where(
                CrmDeal.assigned_by_id.in_(manager_ids),
                CrmDeal.closed.is_(False),
                CrmDeal.missing_from_bitrix.is_(False),
                CrmDeal.has_future_activity.is_(False),
            )
            .group_by(CrmDeal.assigned_by_id)
        )
    ).all()
    no_future_map = {mid: int(c) for mid, c in no_future}

    out: dict[int, dict[str, int]] = {}
    for mid in manager_ids:
        created_n = created_map.get(mid, 0)
        completed_n = completed_map.get(mid, 0)
        changed_n = changed_deal_count.get(mid, 0)
        out[mid] = {
            "created_deals": created_n,
            "changed_deals": changed_n,
            "completed_activities": completed_n,
            "stage_changes": stage_changes.get(mid, 0),
            "opportunity_changes": opportunity_changes.get(mid, 0),
            "crm_actions_today": created_n + completed_n + changed_n,
            "overdue_activities": len(overdue_sets.get(mid, set())),
            "no_future_activity": no_future_map.get(mid, 0),
        }
    return out


def _today_metrics_from_snapshot(
    snap: ManagerWorkdaySnapshot | None,
    *,
    today: date,
    classified: dict[str, Any],
) -> dict[str, Any]:
    """Today start/finish/duration/breaks — only when applicable (not stale EXPIRED)."""
    empty = {
        "time_start": None,
        "time_finish": None,
        "duration_seconds": None,
        "duration_display": None,
        "time_leaks_seconds": None,
        "time_leaks_display": None,
        "available": False,
    }
    if snap is None or not classified.get("today_metrics_applicable"):
        return empty
    if classified.get("status_normalized") == STATUS_STALE_UNCLOSED:
        return empty
    if classified.get("status_normalized") == STATUS_NO_DATA:
        return empty

    start_day = None
    if snap.time_start is not None:
        ts = snap.time_start if snap.time_start.tzinfo else snap.time_start.replace(tzinfo=timezone.utc)
        start_day = ts.astimezone(app_tz()).date()
    finish_day = None
    if snap.time_finish is not None:
        tf = snap.time_finish if snap.time_finish.tzinfo else snap.time_finish.replace(tzinfo=timezone.utc)
        finish_day = tf.astimezone(app_tz()).date()

    # For working/paused/closed today — only expose times belonging to today
    use_start = snap.time_start if start_day == today else None
    use_finish = snap.time_finish if finish_day == today else None
    use_duration = snap.duration_seconds if (start_day == today or finish_day == today) else None
    use_leaks = snap.time_leaks_seconds if (start_day == today or finish_day == today) else None

    # not_started: available for status, times null
    if classified.get("status_normalized") == "not_started":
        return {
            "time_start": None,
            "time_finish": None,
            "duration_seconds": None,
            "duration_display": None,
            "time_leaks_seconds": None,
            "time_leaks_display": None,
            "available": True,
        }

    return {
        "time_start": use_start.isoformat() if use_start else None,
        "time_finish": use_finish.isoformat() if use_finish else None,
        "duration_seconds": use_duration,
        "duration_display": format_seconds(use_duration),
        "time_leaks_seconds": use_leaks,
        "time_leaks_display": format_seconds(use_leaks),
        "available": True,
    }


async def list_manager_control(session: AsyncSession) -> dict[str, Any]:
    settings = get_settings()
    today = utc_now().astimezone(app_tz()).date()
    freshness = await get_timeman_freshness(session)

    managers = await list_monitored_managers(session)
    ids = [m.id for m in managers]
    snaps = await _latest_snapshots(session, ids)
    crm = await _crm_metrics_for_managers(session, ids, day=today)

    # Optional today workday rows (history) — not required for current status
    workdays = (
        await session.execute(
            select(ManagerWorkday).where(
                ManagerWorkday.manager_id.in_(ids),
                ManagerWorkday.work_date == today,
            )
        )
    ).scalars().all() if ids else []
    wd_by = {w.manager_id: w for w in workdays}

    open_viols = (
        await session.execute(
            select(WorkdayViolation).where(
                WorkdayViolation.manager_id.in_(ids or [-1]),
                WorkdayViolation.work_date == today,
                WorkdayViolation.state == STATE_OPEN,
            )
        )
    ).scalars().all() if ids else []
    viols_by: dict[int, list[WorkdayViolation]] = {}
    for v in open_viols:
        viols_by.setdefault(v.manager_id, []).append(v)

    policy = await get_or_create_policy(session)

    items = []
    for m in managers:
        snap = snaps.get(m.id)
        classified = classify_current_status(
            status_raw=snap.status_raw if snap else None,
            time_start=snap.time_start if snap else None,
            time_finish=snap.time_finish if snap else None,
            observed_at=snap.observed_at if snap else None,
            today=today,
        )
        today_m = _today_metrics_from_snapshot(snap, today=today, classified=classified)
        metrics = crm.get(m.id, {})
        last_poll = None
        last_poll_local = None
        if snap is not None:
            last_poll = snap.observed_at.isoformat()
            last_poll_local = _as_utc(snap.observed_at).astimezone(app_tz()).strftime("%H:%M")

        sch, plan = await resolve_day_plan_for_manager(session, m.id, today)
        mv = viols_by.get(m.id, [])
        badges = []
        for v in mv[:3]:
            label = violation_label_ru(v.violation_type)
            if v.violation_type == "LATE_START" and v.details and v.details.get("late_minutes") is not None:
                label = f"Опоздание {v.details['late_minutes']} мин"
            badges.append({"type": v.violation_type, "label": label, "severity": v.severity, "is_preview": v.is_preview})

        items.append(
            {
                "id": m.id,
                "bitrix_id": m.bitrix_id,
                "name": m.name,
                "last_name": m.last_name,
                "display_name": f"{m.name} {m.last_name}".strip(),
                "bitrix_user_active": m.is_active,
                "monitored": True,
                "status_normalized": classified["status_normalized"],
                "status_label": classified["status_label"],
                "is_stale_unclosed": classified["is_stale_unclosed"],
                "stale_since_date": classified["stale_since_date"],
                "stale_since_label": classified["stale_since_label"],
                "status_tooltip": classified["tooltip"],
                "time_start": today_m["time_start"],
                "time_finish": today_m["time_finish"],
                "duration_seconds": today_m["duration_seconds"],
                "duration_display": today_m["duration_display"],
                "time_leaks_seconds": today_m["time_leaks_seconds"],
                "time_leaks_display": today_m["time_leaks_display"],
                "today_metrics_available": today_m["available"],
                "crm_actions_today": metrics.get("crm_actions_today", 0),
                "overdue_activities": metrics.get("overdue_activities", 0),
                "no_future_activity": metrics.get("no_future_activity", 0),
                "last_timeman_poll_at": last_poll,
                "last_timeman_poll_local": last_poll_local,
                "has_snapshot": snap is not None,
                "workday_today_row": wd_by.get(m.id) is not None,
                "schedule": (
                    {
                        "id": sch.id,
                        "name": sch.name,
                        "configured": True,
                        "start": plan.start_hm if plan else None,
                        "end": plan.end_hm if plan else None,
                        "is_working": bool(plan and plan.is_working),
                    }
                    if sch
                    else {"configured": False, "label": "Рабочий график не настроен"}
                ),
                "violations_count": len(mv),
                "violation_badges": badges,
                "has_violations": len(mv) > 0,
            }
        )

    return {
        "date": today.isoformat(),
        "timezone": settings.APP_TIMEZONE,
        "freshness": freshness,
        "policy": {
            "enforcement_start_date": (
                policy.enforcement_start_date.isoformat() if policy.enforcement_start_date else None
            ),
        },
        "items": items,
        "total": len(items),
        "limitations": {
            "time_control": False,
            "note": "Контроль присутствия Time Control в Bitrix24 выключен. Простои и офлайн недоступны. Рабочее время берётся из Timeman.",
        },
    }


async def get_manager_control_detail(
    session: AsyncSession,
    manager_id: int,
) -> dict[str, Any] | None:
    settings = get_settings()
    manager = await session.get(CrmManager, manager_id)
    if manager is None:
        return None

    today = utc_now().astimezone(app_tz()).date()
    freshness = await get_timeman_freshness(session)
    history_since_raw = freshness.get("history_since")
    history_since_date: date | None = None
    if history_since_raw:
        try:
            history_since_date = date.fromisoformat(str(history_since_raw)[:10])
        except ValueError:
            history_since_date = None

    snaps = await _latest_snapshots(session, [manager_id])
    snap = snaps.get(manager_id)
    classified = classify_current_status(
        status_raw=snap.status_raw if snap else None,
        time_start=snap.time_start if snap else None,
        time_finish=snap.time_finish if snap else None,
        observed_at=snap.observed_at if snap else None,
        today=today,
    )
    today_m = _today_metrics_from_snapshot(snap, today=today, classified=classified)

    crm = await _crm_metrics_for_managers(session, [manager_id], day=today)
    metrics = crm.get(manager_id, {})

    timeline = []
    if today_m["available"] and classified["status_normalized"] != STATUS_STALE_UNCLOSED:
        timeline = build_simple_timeline(
            time_start=snap.time_start if snap and today_m["time_start"] else None,
            time_finish=snap.time_finish if snap and today_m["time_finish"] else None,
            duration_seconds=today_m["duration_seconds"],
            time_leaks_seconds=today_m["time_leaks_seconds"],
            status_normalized=classified["status_normalized"],
        )

    week_dates = local_dates_back(7, today=today)
    week_rows = (
        await session.execute(
            select(ManagerWorkday).where(
                ManagerWorkday.manager_id == manager_id,
                ManagerWorkday.work_date.in_(week_dates),
            )
        )
    ).scalars().all()
    wd_week = {w.work_date: w for w in week_rows}

    week_crm: dict[date, dict[str, int]] = {}
    for d in week_dates:
        day_metrics = await _crm_metrics_for_managers(session, [manager_id], day=d)
        week_crm[d] = day_metrics.get(manager_id, {})

    hist_note = freshness.get("history_since_note")
    week: list[dict[str, Any]] = []
    for d in week_dates:
        wd = wd_week.get(d)
        before_history = history_since_date is not None and d < history_since_date
        if before_history or wd is None:
            week.append(
                {
                    "date": d.isoformat(),
                    "workday_available": False,
                    "missing_reason": "before_history" if before_history else "not_collected",
                    "note": hist_note,
                    "time_start": None,
                    "time_finish": None,
                    "duration_display": None,
                    "time_leaks_display": None,
                    "status_label": None,
                    "crm_activity": week_crm.get(d, {}),
                    "show_as_zero_workday": False,
                }
            )
        else:
            week.append(
                {
                    "date": d.isoformat(),
                    "workday_available": True,
                    "missing_reason": None,
                    "note": None,
                    "status_normalized": wd.status_normalized,
                    "status_label": status_label_ru(wd.status_normalized),
                    "time_start": wd.time_start.isoformat() if wd.time_start else None,
                    "time_finish": wd.time_finish.isoformat() if wd.time_finish else None,
                    "duration_seconds": wd.duration_seconds,
                    "duration_display": format_seconds(wd.duration_seconds),
                    "time_leaks_seconds": wd.time_leaks_seconds,
                    "time_leaks_display": format_seconds(wd.time_leaks_seconds),
                    "crm_activity": week_crm.get(d, {}),
                    "show_as_zero_workday": False,
                }
            )

    last_poll = snap.observed_at.isoformat() if snap else None
    last_poll_local = (
        _as_utc(snap.observed_at).astimezone(app_tz()).strftime("%H:%M") if snap else None
    )

    sch, plan = await resolve_day_plan_for_manager(session, manager_id, today)
    policy = await get_or_create_policy(session)
    viol_rows = (
        await session.execute(
            select(WorkdayViolation).where(
                WorkdayViolation.manager_id == manager_id,
                WorkdayViolation.work_date == today,
            )
        )
    ).scalars().all()

    return {
        "id": manager.id,
        "bitrix_id": manager.bitrix_id,
        "name": manager.name,
        "last_name": manager.last_name,
        "display_name": f"{manager.name} {manager.last_name}".strip(),
        "bitrix_user_active": manager.is_active,
        "date": today.isoformat(),
        "timezone": settings.APP_TIMEZONE,
        "freshness": freshness,
        "policy": {
            "enforcement_start_date": (
                policy.enforcement_start_date.isoformat() if policy.enforcement_start_date else None
            ),
        },
        "today": {
            "current_status": {
                "status_normalized": classified["status_normalized"],
                "status_label": classified["status_label"],
                "is_stale_unclosed": classified["is_stale_unclosed"],
                "stale_since_date": classified["stale_since_date"],
                "stale_since_label": classified["stale_since_label"],
                "tooltip": classified["tooltip"],
                "has_snapshot": snap is not None,
                "last_timeman_poll_at": last_poll,
                "last_timeman_poll_local": last_poll_local,
            },
            "schedule": (
                {
                    "configured": True,
                    "id": sch.id,
                    "name": sch.name,
                    "planned_start": plan.start_hm if plan else None,
                    "planned_end": plan.end_hm if plan else None,
                    "required_minutes": plan.required_minutes if plan else None,
                    "is_working": bool(plan and plan.is_working),
                    "kind": plan.kind if plan else None,
                }
                if sch
                else {"configured": False, "label": "Рабочий график не настроен"}
            ),
            "workday": {
                "available": today_m["available"],
                "time_start": today_m["time_start"],
                "time_finish": today_m["time_finish"],
                "duration_seconds": today_m["duration_seconds"],
                "duration_display": today_m["duration_display"],
                "time_leaks_seconds": today_m["time_leaks_seconds"],
                "time_leaks_display": today_m["time_leaks_display"],
                "note": (
                    f"Незакрытый рабочий день {classified['stale_since_label']}"
                    if classified["is_stale_unclosed"]
                    else None
                ),
            },
            "timeline": timeline,
            "crm_activity": {
                "created_deals": metrics.get("created_deals", 0),
                "changed_deals": metrics.get("changed_deals", 0),
                "completed_activities": metrics.get("completed_activities", 0),
                "stage_changes": metrics.get("stage_changes", 0),
                "opportunity_changes": metrics.get("opportunity_changes", 0),
                "overdue_activities": metrics.get("overdue_activities", 0),
                "no_future_activity": metrics.get("no_future_activity", 0),
            },
            "violations": {
                "open": [
                    {
                        "type": v.violation_type,
                        "label": violation_label_ru(v.violation_type),
                        "severity": v.severity,
                        "threshold": v.threshold_value,
                        "actual": v.actual_value,
                        "details": v.details,
                        "is_preview": v.is_preview,
                        "detected_at": v.detected_at.isoformat(),
                    }
                    for v in viol_rows
                    if v.state == STATE_OPEN
                ],
                "resolved": [
                    {
                        "type": v.violation_type,
                        "label": violation_label_ru(v.violation_type),
                        "severity": v.severity,
                        "resolved_at": v.resolved_at.isoformat() if v.resolved_at else None,
                        "is_preview": v.is_preview,
                    }
                    for v in viol_rows
                    if v.state != STATE_OPEN
                ],
            },
        },
        "week": week,
        "limitations": {
            "time_control": False,
            "note": "Контроль присутствия Time Control в Bitrix24 выключен. Простои и офлайн недоступны. Рабочее время — Timeman, CRM считается отдельно.",
        },
    }

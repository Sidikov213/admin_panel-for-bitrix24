"""Week / month / team reports for Manager Control V3."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import app_tz, utc_now
from app.models.manager_control import ManagerWorkday
from app.models.work_schedules import WorkdayViolation
from app.services.manager_control_service import _crm_metrics_for_managers, get_timeman_freshness
from app.services.monitored_roster import list_monitored_managers
from app.services.schedule_service import resolve_day_plan_for_manager
from app.services.timeman_collector import STATE_HISTORY_SINCE
from app.repositories.sync import SyncRepository
from app.services.timeman_parse import format_seconds
from app.services.workday_rules import STATE_OPEN, violation_label_ru


async def _history_since(session: AsyncSession) -> date | None:
    hist = await SyncRepository(session).get_state(STATE_HISTORY_SINCE) or {}
    raw = hist.get("local_date")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _daterange(start: date, end: date) -> list[date]:
    out = []
    d = start
    while d <= end:
        out.append(d)
        d += timedelta(days=1)
    return out


async def week_report(session: AsyncSession, manager_id: int, *, anchor: date | None = None) -> dict[str, Any]:
    today = utc_now().astimezone(app_tz()).date()
    anchor = anchor or today
    # Monday-start week
    start = anchor - timedelta(days=anchor.weekday())
    end = start + timedelta(days=6)
    history_since = await _history_since(session)

    workdays = (
        await session.execute(
            select(ManagerWorkday).where(
                ManagerWorkday.manager_id == manager_id,
                ManagerWorkday.work_date >= start,
                ManagerWorkday.work_date <= end,
            )
        )
    ).scalars().all()
    wd_by = {w.work_date: w for w in workdays}

    viols = (
        await session.execute(
            select(WorkdayViolation).where(
                WorkdayViolation.manager_id == manager_id,
                WorkdayViolation.work_date >= start,
                WorkdayViolation.work_date <= end,
            )
        )
    ).scalars().all()
    viols_by: dict[date, list[WorkdayViolation]] = {}
    for v in viols:
        viols_by.setdefault(v.work_date, []).append(v)

    rows = []
    plan_minutes_total = 0
    fact_seconds_total = 0
    working_days = 0
    late_n = 0
    not_closed_n = 0
    viol_n = 0
    days_with_data = 0

    for d in _daterange(start, end):
        sch, plan = await resolve_day_plan_for_manager(session, manager_id, d)
        wd = wd_by.get(d)
        day_viols = viols_by.get(d, [])
        open_viols = [v for v in day_viols if v.state == STATE_OPEN]
        crm = (await _crm_metrics_for_managers(session, [manager_id], day=d)).get(manager_id, {})

        no_history = history_since is not None and d < history_since
        if wd is not None:
            days_with_data += 1

        if plan and plan.is_working:
            working_days += 1
            if plan.required_minutes:
                plan_minutes_total += plan.required_minutes

        if wd and wd.duration_seconds:
            fact_seconds_total += wd.duration_seconds

        late = next((v for v in day_viols if v.violation_type == "LATE_START"), None)
        if late:
            late_n += 1
        if any(v.violation_type == "WORKDAY_NOT_CLOSED" for v in day_viols):
            not_closed_n += 1
        viol_n += len(open_viols)

        rows.append(
            {
                "date": d.isoformat(),
                "plan": (
                    None
                    if sch is None
                    else {
                        "schedule_name": plan.schedule_name if plan else None,
                        "is_working": bool(plan and plan.is_working),
                        "start": plan.start_hm if plan else None,
                        "end": plan.end_hm if plan else None,
                        "required_minutes": plan.required_minutes if plan else None,
                        "kind": plan.kind if plan else None,
                    }
                ),
                "schedule_configured": sch is not None,
                "time_start": wd.time_start.isoformat() if wd and wd.time_start else None,
                "time_finish": wd.time_finish.isoformat() if wd and wd.time_finish else None,
                "duration_seconds": wd.duration_seconds if wd else None,
                "duration_display": format_seconds(wd.duration_seconds) if wd else None,
                "time_leaks_seconds": wd.time_leaks_seconds if wd else None,
                "time_leaks_display": format_seconds(wd.time_leaks_seconds) if wd else None,
                "late_minutes": (late.details or {}).get("late_minutes") if late else None,
                "shortfall_minutes": next(
                    (
                        (v.details or {}).get("required_minutes", 0)
                        - (v.details or {}).get("actual_minutes", 0)
                        for v in day_viols
                        if v.violation_type == "SHORT_WORKDAY"
                    ),
                    None,
                ),
                "violations": [
                    {
                        "type": v.violation_type,
                        "label": violation_label_ru(v.violation_type),
                        "state": v.state,
                        "severity": v.severity,
                        "is_preview": v.is_preview,
                    }
                    for v in day_viols
                ],
                "crm_actions": crm.get("crm_actions_today", 0),
                "no_historical_data": no_history and wd is None,
                "missing_data_label": (
                    "Нет исторических данных Focus Analytics" if (no_history and wd is None) else None
                ),
            }
        )

    return {
        "manager_id": manager_id,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "rows": rows,
        "totals": {
            "working_days": working_days,
            "days_with_data": days_with_data,
            "plan_minutes": plan_minutes_total,
            "fact_seconds": fact_seconds_total,
            "fact_display": format_seconds(fact_seconds_total),
            "delta_minutes": (fact_seconds_total // 60) - plan_minutes_total,
            "late_count": late_n,
            "not_closed_count": not_closed_n,
            "open_violations": viol_n,
        },
        "freshness": await get_timeman_freshness(session),
        "limitations": {
            "time_control": False,
            "note": "Рабочее время — Bitrix Timeman. Активность в CRM — отдельная метрика. Простои и офлайн недоступны.",
        },
    }


async def month_report(
    session: AsyncSession, manager_id: int, *, year: int, month: int
) -> dict[str, Any]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    history_since = await _history_since(session)
    workdays = (
        await session.execute(
            select(ManagerWorkday).where(
                ManagerWorkday.manager_id == manager_id,
                ManagerWorkday.work_date >= start,
                ManagerWorkday.work_date <= end,
            )
        )
    ).scalars().all()
    wd_by = {w.work_date: w for w in workdays}

    viol_rows = (
        await session.execute(
            select(WorkdayViolation.violation_type, func.count())
            .where(
                WorkdayViolation.manager_id == manager_id,
                WorkdayViolation.work_date >= start,
                WorkdayViolation.work_date <= end,
                WorkdayViolation.state == STATE_OPEN,
            )
            .group_by(WorkdayViolation.violation_type)
        )
    ).all()
    viol_counts = {t: int(c) for t, c in viol_rows}

    plan_days = 0
    plan_minutes = 0
    fact_seconds = 0
    marked_days = 0
    for d in _daterange(start, end):
        if history_since and d < history_since:
            continue
        _, plan = await resolve_day_plan_for_manager(session, manager_id, d)
        if plan and plan.is_working:
            plan_days += 1
            if plan.required_minutes:
                plan_minutes += plan.required_minutes
        wd = wd_by.get(d)
        if wd is not None:
            marked_days += 1
            if wd.duration_seconds:
                fact_seconds += wd.duration_seconds

    return {
        "manager_id": manager_id,
        "period": {"start": start.isoformat(), "end": end.isoformat(), "year": year, "month": month},
        "plan_working_days": plan_days,
        "marked_days": marked_days,
        "plan_minutes": plan_minutes,
        "fact_seconds": fact_seconds,
        "fact_display": format_seconds(fact_seconds),
        "delta_minutes": (fact_seconds // 60) - plan_minutes,
        "late_starts": viol_counts.get("LATE_START", 0),
        "early_finishes": viol_counts.get("EARLY_FINISH", 0),
        "not_closed": viol_counts.get("WORKDAY_NOT_CLOSED", 0) + viol_counts.get("STALE_UNCLOSED_DAY", 0),
        "not_started": viol_counts.get("WORKDAY_NOT_STARTED", 0),
        "total_open_violations": sum(viol_counts.values()),
        "violations_by_type": viol_counts,
        "history_since": history_since.isoformat() if history_since else None,
        "freshness": await get_timeman_freshness(session),
    }


async def team_report(
    session: AsyncSession,
    *,
    start: date,
    end: date,
) -> dict[str, Any]:
    managers = await list_monitored_managers(session)
    ids = [m.id for m in managers]
    history_since = await _history_since(session)

    workday_agg = (
        await session.execute(
            select(
                ManagerWorkday.manager_id,
                func.count(),
                func.coalesce(func.sum(ManagerWorkday.duration_seconds), 0),
            )
            .where(
                ManagerWorkday.manager_id.in_(ids or [-1]),
                ManagerWorkday.work_date >= start,
                ManagerWorkday.work_date <= end,
            )
            .group_by(ManagerWorkday.manager_id)
        )
    ).all()
    wd_map = {mid: {"days": int(c), "seconds": int(s)} for mid, c, s in workday_agg}

    viol_agg = (
        await session.execute(
            select(
                WorkdayViolation.manager_id,
                WorkdayViolation.violation_type,
                func.count(),
            )
            .where(
                WorkdayViolation.manager_id.in_(ids or [-1]),
                WorkdayViolation.work_date >= start,
                WorkdayViolation.work_date <= end,
                WorkdayViolation.state == STATE_OPEN,
            )
            .group_by(WorkdayViolation.manager_id, WorkdayViolation.violation_type)
        )
    ).all()
    viol_map: dict[int, dict[str, int]] = {}
    for mid, vtype, cnt in viol_agg:
        viol_map.setdefault(mid, {})[vtype] = int(cnt)

    # CRM actions summed per day would be heavy; approximate with period bounds via daily loop is N*days.
    # Use single-pass per day batched.
    crm_totals: dict[int, int] = {i: 0 for i in ids}
    for d in _daterange(start, end):
        if history_since and d < history_since:
            continue
        day_crm = await _crm_metrics_for_managers(session, ids, day=d)
        for mid, m in day_crm.items():
            crm_totals[mid] = crm_totals.get(mid, 0) + int(m.get("crm_actions_today", 0))

    items = []
    for m in managers:
        plan_minutes = 0
        plan_days = 0
        for d in _daterange(start, end):
            if history_since and d < history_since:
                continue
            _, plan = await resolve_day_plan_for_manager(session, m.id, d)
            if plan and plan.is_working:
                plan_days += 1
                if plan.required_minutes:
                    plan_minutes += plan.required_minutes
        w = wd_map.get(m.id, {"days": 0, "seconds": 0})
        v = viol_map.get(m.id, {})
        items.append(
            {
                "id": m.id,
                "display_name": f"{m.name} {m.last_name}".strip(),
                "working_days_plan": plan_days,
                "marked_days": w["days"],
                "plan_minutes": plan_minutes,
                "fact_seconds": w["seconds"],
                "fact_display": format_seconds(w["seconds"]),
                "delta_minutes": (w["seconds"] // 60) - plan_minutes,
                "late_starts": v.get("LATE_START", 0),
                "not_closed": v.get("WORKDAY_NOT_CLOSED", 0) + v.get("STALE_UNCLOSED_DAY", 0),
                "open_violations": sum(v.values()),
                "crm_actions": crm_totals.get(m.id, 0),
            }
        )

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "items": items,
        "total": len(items),
        "freshness": await get_timeman_freshness(session),
        "csv_headers": [
            "manager",
            "working_days_plan",
            "marked_days",
            "plan_minutes",
            "fact_seconds",
            "delta_minutes",
            "late_starts",
            "not_closed",
            "open_violations",
            "crm_actions",
        ],
    }

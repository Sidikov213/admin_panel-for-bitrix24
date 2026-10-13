"""Evaluate and upsert workday violations after Timeman collect (isolated)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import app_tz, utc_now
from app.db.session import async_session_factory
from app.models.manager_control import ManagerWorkday, ManagerWorkdaySnapshot
from app.services.monitored_roster import list_monitored_managers
from app.services.schedule_service import get_or_create_policy, resolve_day_plan_for_manager
from app.services.timeman_parse import STATUS_STALE_UNCLOSED, classify_current_status
from app.services.workday_rules import (
    STATE_OPEN,
    STATE_RESOLVED,
    WorkdayFacts,
    evaluate_day_violations,
    is_enforcement_active,
    severity_for,
)
from app.models.work_schedules import WorkdayViolation

logger = logging.getLogger(__name__)


def _facts_from_row(
    *,
    status_normalized: str | None,
    time_start: datetime | None,
    time_finish: datetime | None,
    duration_seconds: int | None,
    time_leaks_seconds: int | None,
    is_stale: bool,
) -> WorkdayFacts:
    return WorkdayFacts(
        status_normalized=status_normalized,
        time_start=time_start,
        time_finish=time_finish,
        duration_seconds=duration_seconds,
        time_leaks_seconds=time_leaks_seconds,
        is_stale_unclosed=is_stale,
    )


async def _upsert_violations(
    session: AsyncSession,
    *,
    manager_id: int,
    work_date: date,
    schedule_id: int | None,
    candidates: list,
    severity_map: dict[str, str] | None,
    preview: bool,
    now: datetime,
) -> tuple[int, int]:
    """Returns (opened_or_kept, resolved)."""
    active_types = {c.violation_type for c in candidates}
    existing = (
        await session.execute(
            select(WorkdayViolation).where(
                WorkdayViolation.manager_id == manager_id,
                WorkdayViolation.work_date == work_date,
            )
        )
    ).scalars().all()
    by_type = {v.violation_type: v for v in existing}
    opened = 0
    resolved = 0

    for c in candidates:
        sev = severity_for(c.violation_type, severity_map)
        row = by_type.get(c.violation_type)
        if row is None:
            session.add(
                WorkdayViolation(
                    manager_id=manager_id,
                    work_date=work_date,
                    violation_type=c.violation_type,
                    state=STATE_OPEN,
                    severity=sev,
                    detected_at=now,
                    resolved_at=None,
                    threshold_value=c.threshold_value,
                    actual_value=c.actual_value,
                    schedule_id=schedule_id,
                    details=c.details,
                    is_preview=preview,
                )
            )
            opened += 1
        else:
            row.state = STATE_OPEN
            row.severity = sev
            row.threshold_value = c.threshold_value
            row.actual_value = c.actual_value
            row.schedule_id = schedule_id
            row.details = c.details
            row.is_preview = preview
            row.resolved_at = None
            opened += 1

    for vtype, row in by_type.items():
        if vtype not in active_types and row.state == STATE_OPEN:
            row.state = STATE_RESOLVED
            row.resolved_at = now
            resolved += 1

    return opened, resolved


async def evaluate_manager_day(
    session: AsyncSession,
    manager_id: int,
    day: date,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or utc_now()
    policy = await get_or_create_policy(session)
    sch, plan = await resolve_day_plan_for_manager(session, manager_id, day)
    preview = not is_enforcement_active(policy.enforcement_start_date, day)

    # Prefer aggregated workday row; fall back to latest snapshot classification
    wd = (
        await session.execute(
            select(ManagerWorkday).where(
                ManagerWorkday.manager_id == manager_id,
                ManagerWorkday.work_date == day,
            )
        )
    ).scalar_one_or_none()

    snap = (
        await session.execute(
            select(ManagerWorkdaySnapshot)
            .where(ManagerWorkdaySnapshot.manager_id == manager_id)
            .order_by(ManagerWorkdaySnapshot.observed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    today = now.astimezone(app_tz()).date()
    classified = classify_current_status(
        status_raw=snap.status_raw if snap else None,
        time_start=snap.time_start if snap else (wd.time_start if wd else None),
        time_finish=snap.time_finish if snap else (wd.time_finish if wd else None),
        observed_at=snap.observed_at if snap else (wd.last_observed_at if wd else None),
        today=today,
    )
    is_stale = bool(classified.get("is_stale_unclosed")) or (
        (wd.status_normalized if wd else None) == STATUS_STALE_UNCLOSED
    )

    facts = _facts_from_row(
        status_normalized=(
            wd.status_normalized if wd else classified.get("status_normalized")
        ),
        time_start=wd.time_start if wd else (snap.time_start if snap else None),
        time_finish=wd.time_finish if wd else (snap.time_finish if snap else None),
        duration_seconds=wd.duration_seconds if wd else (snap.duration_seconds if snap else None),
        time_leaks_seconds=(
            wd.time_leaks_seconds if wd else (snap.time_leaks_seconds if snap else None)
        ),
        is_stale=is_stale,
    )

    candidates = evaluate_day_violations(plan, facts, day=day, now=now)
    # STALE without schedule still allowed; other types require plan
    if plan is None:
        candidates = [c for c in candidates if c.violation_type == "STALE_UNCLOSED_DAY"]

    opened, resolved = await _upsert_violations(
        session,
        manager_id=manager_id,
        work_date=day,
        schedule_id=sch.id if sch else None,
        candidates=candidates,
        severity_map=policy.severity_by_type,
        preview=preview,
        now=now,
    )
    return {
        "manager_id": manager_id,
        "day": day.isoformat(),
        "schedule_id": sch.id if sch else None,
        "has_schedule": sch is not None,
        "is_working_day": bool(plan and plan.is_working),
        "candidates": len(candidates),
        "upserted": opened,
        "resolved": resolved,
        "is_preview": preview,
    }


async def run_violation_evaluation(
    session: AsyncSession,
    *,
    days_back: int = 2,
) -> dict[str, Any]:
    """Evaluate today + recent local days for all monitored managers."""
    now = utc_now()
    today = now.astimezone(app_tz()).date()
    managers = await list_monitored_managers(session)
    results = []
    errors = 0
    for m in managers:
        for offset in range(0, max(1, days_back)):
            day = today - timedelta(days=offset)
            try:
                results.append(await evaluate_manager_day(session, m.id, day, now=now))
            except Exception:
                errors += 1
                logger.exception("violation_eval_manager_failed manager_id=%s day=%s", m.id, day)
    await session.commit()
    return {
        "ok": errors == 0,
        "managers": len(managers),
        "evaluated": len(results),
        "errors": errors,
        "results": results,
    }


async def run_violation_evaluation_safe() -> dict[str, Any]:
    """Never raises — own session. Safe after Timeman collect."""
    try:
        async with async_session_factory() as session:
            return await run_violation_evaluation(session)
    except Exception as exc:
        logger.exception("violation_evaluation_safe_failed")
        return {"ok": False, "error_message": type(exc).__name__, "errors": 1}


async def preview_schedule_last_days(
    session: AsyncSession,
    schedule_id: int,
    manager_id: int,
    *,
    days: int = 7,
) -> dict[str, Any]:
    """What-if: apply schedule to available Timeman history only (no invented days)."""
    from app.models.work_schedules import WorkSchedule
    from app.services.schedule_service import schedule_to_spec
    from app.services.workday_rules import build_day_plan

    sch = await session.get(WorkSchedule, schedule_id)
    if sch is None:
        raise ValueError("schedule_not_found")

    now = utc_now()
    today = now.astimezone(app_tz()).date()
    spec = schedule_to_spec(sch)

    workdays = (
        await session.execute(
            select(ManagerWorkday).where(
                ManagerWorkday.manager_id == manager_id,
                ManagerWorkday.work_date >= today - timedelta(days=days - 1),
                ManagerWorkday.work_date <= today,
            )
        )
    ).scalars().all()
    if not workdays:
        return {
            "manager_id": manager_id,
            "schedule_id": schedule_id,
            "days_with_data": 0,
            "message": "Нет исторических данных Focus Analytics",
            "late_starts": 0,
            "not_closed": 0,
            "short_days": 0,
            "not_started": 0,
            "total_violations": 0,
        }

    counts = {
        "LATE_START": 0,
        "WORKDAY_NOT_CLOSED": 0,
        "SHORT_WORKDAY": 0,
        "WORKDAY_NOT_STARTED": 0,
    }
    for wd in workdays:
        plan = build_day_plan(spec, day=wd.work_date)
        facts = _facts_from_row(
            status_normalized=wd.status_normalized,
            time_start=wd.time_start,
            time_finish=wd.time_finish,
            duration_seconds=wd.duration_seconds,
            time_leaks_seconds=wd.time_leaks_seconds,
            is_stale=wd.status_normalized == STATUS_STALE_UNCLOSED,
        )
        # Evaluate as of end-of-day + grace for historical preview
        end_of_eval = datetime.combine(
            wd.work_date, datetime.max.time(), tzinfo=app_tz()
        ).astimezone(wd.time_start.tzinfo if wd.time_start and wd.time_start.tzinfo else app_tz())
        cands = evaluate_day_violations(plan, facts, day=wd.work_date, now=now if wd.work_date == today else end_of_eval)
        for c in cands:
            if c.violation_type in counts:
                counts[c.violation_type] += 1

    total = sum(counts.values())
    return {
        "manager_id": manager_id,
        "schedule_id": schedule_id,
        "days_with_data": len(workdays),
        "late_starts": counts["LATE_START"],
        "not_closed": counts["WORKDAY_NOT_CLOSED"],
        "short_days": counts["SHORT_WORKDAY"],
        "not_started": counts["WORKDAY_NOT_STARTED"],
        "total_violations": total,
        "message": (
            f"Если применить этот график за последние доступные {len(workdays)} дн. с данными Timeman"
        ),
    }

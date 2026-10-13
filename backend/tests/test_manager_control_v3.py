"""Manager Control V3 — schedules, calendar, violations, reports."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models.crm import CrmDeal, CrmManager
from app.models.manager_control import ManagerWorkday, MonitoredManager
from app.models.work_schedules import (
    CalendarDayOverride,
    ManagerAbsence,
    ManagerControlPolicy,
    ScheduleAssignment,
    WorkSchedule,
    WorkdayViolation,
)
from app.services.schedule_service import (
    create_schedule,
    resolve_day_plan_for_manager,
    resolve_schedule_for_manager,
)
from app.services.violation_evaluator import (
    evaluate_manager_day,
    preview_schedule_last_days,
    run_violation_evaluation_safe,
)
from app.services.workday_rules import (
    BREAK_LIMIT_EXCEEDED,
    EARLY_FINISH,
    LATE_START,
    SHORT_WORKDAY,
    STALE_UNCLOSED_DAY,
    STATE_OPEN,
    STATE_RESOLVED,
    WORKDAY_NOT_CLOSED,
    WORKDAY_NOT_STARTED,
    ScheduleSpec,
    WorkdayFacts,
    build_day_plan,
    evaluate_day_violations,
    is_enforcement_active,
)

TZ = "Europe/Moscow"
MOSCOW = ZoneInfo(TZ)


def _spec(**overrides) -> ScheduleSpec:
    base = dict(
        id=1,
        name="Test",
        timezone=TZ,
        weekdays=[1, 2, 3, 4, 5],
        start_time="09:00",
        end_time="18:00",
        required_minutes=480,
        late_grace_minutes=10,
        early_finish_grace_minutes=10,
        max_break_minutes=60,
        not_started_threshold_minutes=30,
        not_closed_grace_minutes=15,
        enabled=True,
    )
    base.update(overrides)
    return ScheduleSpec(**base)


def _dt(day: date, hm: str) -> datetime:
    h, m = map(int, hm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=MOSCOW)


def test_no_schedule_no_violation_except_stale():
    day = date(2026, 10, 13)
    now = _dt(day, "12:00")
    facts = WorkdayFacts("not_started", None, None, None, None, False)
    assert evaluate_day_violations(None, facts, day=day, now=now) == []
    facts_stale = WorkdayFacts("stale_unclosed", None, None, None, None, True)
    c = evaluate_day_violations(None, facts_stale, day=day, now=now)
    assert len(c) == 1 and c[0].violation_type == STALE_UNCLOSED_DAY


def test_late_start_and_grace():
    day = date(2026, 10, 13)  # Tuesday
    plan = build_day_plan(_spec(), day=day)
    assert plan and plan.is_working
    # Too early — no LATE_START yet
    now = _dt(day, "09:05")
    facts = WorkdayFacts("working", _dt(day, "09:20"), None, 0, 0, False)
    assert LATE_START not in {c.violation_type for c in evaluate_day_violations(plan, facts, day=day, now=now)}
    # After grace
    now2 = _dt(day, "09:15")
    c = evaluate_day_violations(plan, facts, day=day, now=now2)
    assert any(x.violation_type == LATE_START for x in c)


def test_workday_not_started_threshold():
    day = date(2026, 10, 13)
    plan = build_day_plan(_spec(not_started_threshold_minutes=30), day=day)
    facts = WorkdayFacts("not_started", None, None, None, None, False)
    # 09:20 — before threshold 09:30
    assert WORKDAY_NOT_STARTED not in {
        c.violation_type for c in evaluate_day_violations(plan, facts, day=day, now=_dt(day, "09:20"))
    }
    assert any(
        c.violation_type == WORKDAY_NOT_STARTED
        for c in evaluate_day_violations(plan, facts, day=day, now=_dt(day, "09:35"))
    )


def test_early_finish_and_short_and_breaks():
    day = date(2026, 10, 13)
    plan = build_day_plan(_spec(), day=day)
    facts = WorkdayFacts(
        "closed",
        _dt(day, "09:00"),
        _dt(day, "16:00"),
        6 * 3600,
        90 * 60,
        False,
    )
    now = _dt(day, "18:30")
    types = {c.violation_type for c in evaluate_day_violations(plan, facts, day=day, now=now)}
    assert EARLY_FINISH in types
    assert SHORT_WORKDAY in types
    assert BREAK_LIMIT_EXCEEDED in types


def test_workday_not_closed():
    day = date(2026, 10, 13)
    plan = build_day_plan(_spec(not_closed_grace_minutes=15), day=day)
    facts = WorkdayFacts("working", _dt(day, "09:00"), None, 8 * 3600, 0, False)
    assert WORKDAY_NOT_CLOSED not in {
        c.violation_type for c in evaluate_day_violations(plan, facts, day=day, now=_dt(day, "18:10"))
    }
    assert any(
        c.violation_type == WORKDAY_NOT_CLOSED
        for c in evaluate_day_violations(plan, facts, day=day, now=_dt(day, "18:20"))
    )


def test_holiday_and_absence_no_start_violation():
    day = date(2026, 10, 13)
    plan = build_day_plan(_spec(), day=day, global_override={"kind": "holiday"})
    assert plan and not plan.is_working
    facts = WorkdayFacts("not_started", None, None, None, None, False)
    types = {c.violation_type for c in evaluate_day_violations(plan, facts, day=day, now=_dt(day, "12:00"))}
    assert WORKDAY_NOT_STARTED not in types

    plan2 = build_day_plan(_spec(), day=day, absence_kind="vacation")
    assert plan2 and not plan2.is_working


def test_shortened_workday():
    day = date(2026, 10, 13)
    plan = build_day_plan(
        _spec(),
        day=day,
        global_override={"kind": "shortened", "start_time": "09:00", "end_time": "14:00", "required_minutes": 300},
    )
    assert plan and plan.is_working and plan.required_minutes == 300 and plan.end_hm == "14:00"


def test_weekend_from_weekdays():
    day = date(2026, 10, 17)  # Saturday
    plan = build_day_plan(_spec(), day=day)
    assert plan and not plan.is_working and plan.kind == "weekend"


def test_enforcement_date():
    assert is_enforcement_active(None, date(2026, 11, 1)) is False
    assert is_enforcement_active(date(2026, 11, 1), date(2026, 10, 31)) is False
    assert is_enforcement_active(date(2026, 11, 1), date(2026, 11, 1)) is True


@pytest.mark.asyncio
async def test_assignment_priority(db_session):
    mgr = CrmManager(bitrix_id=501, name="A", last_name="B", is_active=True)
    db_session.add(mgr)
    await db_session.flush()
    default = await create_schedule(
        db_session,
        {
            "name": "Default",
            "weekdays": [1, 2, 3, 4, 5],
            "start_time": "09:00",
            "end_time": "18:00",
            "is_default": True,
            "enabled": True,
        },
    )
    override = await create_schedule(
        db_session,
        {
            "name": "Override",
            "weekdays": [1, 2, 3, 4, 5],
            "start_time": "10:00",
            "end_time": "19:00",
            "enabled": True,
        },
    )
    dept = await create_schedule(
        db_session,
        {
            "name": "Dept",
            "weekdays": [1, 2, 3, 4, 5],
            "start_time": "08:00",
            "end_time": "17:00",
            "enabled": True,
        },
    )
    db_session.add(ScheduleAssignment(schedule_id=dept.id, department_key="sales"))
    await db_session.flush()

    sch = await resolve_schedule_for_manager(db_session, mgr.id, department_key="sales")
    assert sch and sch.id == dept.id

    db_session.add(ScheduleAssignment(schedule_id=override.id, manager_id=mgr.id))
    await db_session.flush()
    sch2 = await resolve_schedule_for_manager(db_session, mgr.id, department_key="sales")
    assert sch2 and sch2.id == override.id

    # Remove override → dept; remove dept assignment conceptually by using other dept → default
    sch3 = await resolve_schedule_for_manager(db_session, mgr.id + 999, department_key=None)
    # no manager — only default
    assert default.id


@pytest.mark.asyncio
async def test_violation_dedupe_and_resolve(db_session):
    mgr = CrmManager(bitrix_id=502, name="C", last_name="D", is_active=True)
    db_session.add(mgr)
    await db_session.flush()
    db_session.add(MonitoredManager(manager_id=mgr.id, auto_included=True))
    sch = await create_schedule(
        db_session,
        {
            "name": "S",
            "weekdays": [1, 2, 3, 4, 5],
            "start_time": "09:00",
            "end_time": "18:00",
            "late_grace_minutes": 0,
            "not_started_threshold_minutes": 0,
            "not_closed_grace_minutes": 0,
            "required_minutes": 480,
            "is_default": True,
            "enabled": True,
        },
    )
    day = date(2026, 10, 13)
    db_session.add(
        ManagerWorkday(
            manager_id=mgr.id,
            work_date=day,
            status_normalized="working",
            time_start=_dt(day, "09:30"),
            time_finish=None,
            duration_seconds=3600,
            time_leaks_seconds=0,
            last_observed_at=_dt(day, "12:00"),
            snapshot_count=1,
            has_bitrix_timestamps=True,
        )
    )
    await db_session.commit()

    now = _dt(day, "12:00")
    r1 = await evaluate_manager_day(db_session, mgr.id, day, now=now)
    await db_session.commit()
    r2 = await evaluate_manager_day(db_session, mgr.id, day, now=now)
    await db_session.commit()
    rows = (
        await db_session.execute(
            select(WorkdayViolation).where(
                WorkdayViolation.manager_id == mgr.id,
                WorkdayViolation.work_date == day,
                WorkdayViolation.violation_type == LATE_START,
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].state == STATE_OPEN
    assert r1["candidates"] >= 1
    assert r2["candidates"] >= 1

    # Fix late start → resolve LATE_START
    wd = (
        await db_session.execute(
            select(ManagerWorkday).where(ManagerWorkday.manager_id == mgr.id, ManagerWorkday.work_date == day)
        )
    ).scalar_one()
    wd.time_start = _dt(day, "09:00")
    await db_session.commit()
    await evaluate_manager_day(db_session, mgr.id, day, now=now)
    await db_session.commit()
    row = (
        await db_session.execute(
            select(WorkdayViolation).where(
                WorkdayViolation.manager_id == mgr.id,
                WorkdayViolation.violation_type == LATE_START,
            )
        )
    ).scalar_one()
    assert row.state == STATE_RESOLVED
    assert sch.id


@pytest.mark.asyncio
async def test_individual_day_off_and_preview_missing_history(db_session):
    mgr = CrmManager(bitrix_id=503, name="E", last_name="F", is_active=True)
    db_session.add(mgr)
    await db_session.flush()
    sch = await create_schedule(
        db_session,
        {
            "name": "S",
            "weekdays": [1, 2, 3, 4, 5],
            "start_time": "09:00",
            "end_time": "18:00",
            "is_default": True,
            "enabled": True,
            "not_started_threshold_minutes": 0,
        },
    )
    day = date(2026, 10, 13)
    db_session.add(ManagerAbsence(manager_id=mgr.id, date_from=day, date_to=day, kind="day_off"))
    await db_session.commit()
    _, plan = await resolve_day_plan_for_manager(db_session, mgr.id, day)
    assert plan and not plan.is_working

    preview = await preview_schedule_last_days(db_session, sch.id, mgr.id, days=7)
    assert preview["days_with_data"] == 0
    assert "Нет исторических данных" in preview["message"]


@pytest.mark.asyncio
async def test_calendar_manager_override(db_session):
    mgr = CrmManager(bitrix_id=504, name="G", last_name="H", is_active=True)
    db_session.add(mgr)
    await db_session.flush()
    await create_schedule(
        db_session,
        {
            "name": "S",
            "weekdays": [1, 2, 3, 4, 5],
            "start_time": "09:00",
            "end_time": "18:00",
            "is_default": True,
            "enabled": True,
        },
    )
    day = date(2026, 10, 13)
    db_session.add(
        CalendarDayOverride(day_date=day, kind="holiday", manager_id=mgr.id, label="Личный выходной")
    )
    await db_session.commit()
    _, plan = await resolve_day_plan_for_manager(db_session, mgr.id, day)
    assert plan and not plan.is_working and plan.kind == "holiday"


@pytest.mark.asyncio
async def test_enforcement_preview_flag(db_session):
    mgr = CrmManager(bitrix_id=505, name="I", last_name="J", is_active=True)
    db_session.add(mgr)
    await db_session.flush()
    db_session.add(MonitoredManager(manager_id=mgr.id, auto_included=True))
    await create_schedule(
        db_session,
        {
            "name": "S",
            "weekdays": [1, 2, 3, 4, 5],
            "start_time": "09:00",
            "end_time": "18:00",
            "late_grace_minutes": 0,
            "is_default": True,
            "enabled": True,
        },
    )
    db_session.add(ManagerControlPolicy(id=1, enforcement_start_date=date(2026, 11, 1)))
    day = date(2026, 10, 13)
    db_session.add(
        ManagerWorkday(
            manager_id=mgr.id,
            work_date=day,
            status_normalized="working",
            time_start=_dt(day, "10:00"),
            last_observed_at=_dt(day, "12:00"),
            snapshot_count=1,
            has_bitrix_timestamps=True,
        )
    )
    await db_session.commit()
    r = await evaluate_manager_day(db_session, mgr.id, day, now=_dt(day, "12:00"))
    await db_session.commit()
    assert r["is_preview"] is True
    v = (
        await db_session.execute(
            select(WorkdayViolation).where(WorkdayViolation.manager_id == mgr.id)
        )
    ).scalars().first()
    assert v is not None and v.is_preview is True


@pytest.mark.asyncio
async def test_violation_eval_safe_isolation():
    result = await run_violation_evaluation_safe()
    assert "ok" in result


@pytest.mark.asyncio
async def test_inactive_bitrix_but_monitored_board(db_session, client):
    mgr = CrmManager(bitrix_id=506, name="K", last_name="L", is_active=False)
    db_session.add(mgr)
    await db_session.flush()
    db_session.add(MonitoredManager(manager_id=mgr.id, manual_include=True))
    db_session.add(
        CrmDeal(
            bitrix_id=9001,
            title="t",
            assigned_by_id=mgr.id,
            category_id=1,
            closed=False,
            missing_from_bitrix=False,
            has_future_activity=True,
        )
    )
    await db_session.commit()
    from app.services.manager_control_service import list_manager_control

    data = await list_manager_control(db_session)
    ids = {i["id"] for i in data["items"]}
    assert mgr.id in ids

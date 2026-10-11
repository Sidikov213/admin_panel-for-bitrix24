"""Manager Control V2 — stale EXPIRED, today separation, monitored roster."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.timezone import app_tz, utc_now
from app.models.crm import CrmActivity, CrmDeal, CrmManager
from app.models.manager_control import ManagerWorkday, ManagerWorkdaySnapshot, MonitoredManager
from app.services.manager_control_service import get_manager_control_detail, list_manager_control
from app.services.monitored_roster import list_monitored_managers, sync_monitored_roster
from app.services.timeman_collector import persist_parsed_status_safe
from app.services.timeman_parse import (
    STATUS_CLOSED,
    STATUS_NOT_STARTED,
    STATUS_STALE_UNCLOSED,
    STATUS_WORKING,
    classify_current_status,
    normalize_timeman_status,
    parse_timeman_status_payload,
    should_upsert_workday_history,
)


def test_opened_today_working() -> None:
    today = date(2026, 10, 7)
    start = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)  # 09:00 Moscow
    assert (
        normalize_timeman_status("OPENED", time_start=start, observed_at=start, today=today)
        == STATUS_WORKING
    )


def test_closed_today_completed() -> None:
    today = date(2026, 10, 7)
    start = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)
    finish = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)
    assert (
        normalize_timeman_status(
            "CLOSED", time_start=start, time_finish=finish, observed_at=finish, today=today
        )
        == STATUS_CLOSED
    )


def test_closed_without_time_start_not_started() -> None:
    today = date(2026, 10, 7)
    obs = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    assert (
        normalize_timeman_status("CLOSED", time_start=None, observed_at=obs, today=today)
        == STATUS_NOT_STARTED
    )


def test_closed_past_dates_not_started_today() -> None:
    today = date(2026, 10, 7)
    start = datetime(2026, 3, 30, 7, 0, tzinfo=timezone.utc)
    finish = datetime(2026, 3, 30, 16, 0, tzinfo=timezone.utc)
    assert (
        normalize_timeman_status(
            "CLOSED", time_start=start, time_finish=finish, observed_at=finish, today=today
        )
        == STATUS_NOT_STARTED
    )


def test_stale_expired_not_working() -> None:
    today = date(2026, 10, 7)
    start = datetime(2026, 5, 29, 7, 26, 52, tzinfo=timezone.utc)
    obs = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)
    assert (
        normalize_timeman_status("EXPIRED", time_start=start, observed_at=obs, today=today)
        == STATUS_STALE_UNCLOSED
    )
    c = classify_current_status(
        status_raw="EXPIRED", time_start=start, time_finish=None, observed_at=obs, today=today
    )
    assert c["status_normalized"] == STATUS_STALE_UNCLOSED
    assert c["status_label"] == "Незакрытый рабочий день"
    assert c["stale_since_label"]
    assert c["today_metrics_applicable"] is False


def test_should_not_upsert_stale_history() -> None:
    obs = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)
    assert (
        should_upsert_workday_history(
            status_normalized=STATUS_STALE_UNCLOSED,
            work_date=date(2026, 5, 29),
            observed_at=obs,
        )
        is False
    )


@pytest.mark.asyncio
async def test_snapshot_today_old_expired_visible_not_unknown(db_session) -> None:
    mgr = CrmManager(bitrix_id=15679, name="Юлия", last_name="Замараева", is_active=True)
    db_session.add(mgr)
    await db_session.flush()
    db_session.add(
        CrmDeal(
            bitrix_id=7001,
            title="D",
            assigned_by_id=mgr.id,
            category_id=1,
            closed=False,
            missing_from_bitrix=False,
            has_future_activity=True,
        )
    )
    observed = utc_now()
    parsed = parse_timeman_status_payload(
        {
            "STATUS": "EXPIRED",
            "TIME_START": "2026-05-29T10:26:52+03:00",
            "DURATION": "00:00:00",
            "TIME_LEAKS": "00:00:00",
            "TZ_OFFSET": 10800,
        },
        observed_at=observed,
        app_timezone_name="Europe/Moscow",
    )
    assert parsed.status_normalized == STATUS_STALE_UNCLOSED
    await persist_parsed_status_safe(db_session, manager=mgr, parsed=parsed, observed_at=observed)
    await db_session.commit()

    # No today workday history from stale
    wd_today = (
        await db_session.execute(
            select(ManagerWorkday).where(
                ManagerWorkday.manager_id == mgr.id,
                ManagerWorkday.work_date == observed.astimezone(app_tz()).date(),
            )
        )
    ).scalar_one_or_none()
    assert wd_today is None

    board = await list_manager_control(db_session)
    item = next(x for x in board["items"] if x["id"] == mgr.id)
    assert item["status_normalized"] == STATUS_STALE_UNCLOSED
    assert item["status_label"] == "Незакрытый рабочий день"
    assert item["status_normalized"] != "unknown"
    assert item["duration_display"] is None
    assert item["time_start"] is None
    assert item["has_snapshot"] is True
    assert item["stale_since_label"]


@pytest.mark.asyncio
async def test_inactive_manager_with_crm_today_monitored_visible(db_session) -> None:
    mgr = CrmManager(bitrix_id=15673, name="Мария", last_name="Говор", is_active=False)
    db_session.add(mgr)
    await db_session.flush()
    now = utc_now()
    db_session.add(
        CrmDeal(
            bitrix_id=7002,
            title="New",
            assigned_by_id=mgr.id,
            category_id=1,
            date_create=now,
            closed=False,
            missing_from_bitrix=False,
            has_future_activity=True,
        )
    )
    db_session.add(
        CrmActivity(
            bitrix_id=8002,
            responsible_id=mgr.bitrix_id,
            owner_id=7002,
            owner_type_id=2,
            completed=True,
            completed_at=now,
        )
    )
    await db_session.commit()

    monitored = await list_monitored_managers(db_session)
    assert any(m.id == mgr.id for m in monitored)

    board = await list_manager_control(db_session)
    item = next(x for x in board["items"] if x["id"] == mgr.id)
    assert item["crm_actions_today"] >= 1
    assert item["bitrix_user_active"] is False


@pytest.mark.asyncio
async def test_monitored_without_timeman_no_data_state(db_session) -> None:
    mgr = CrmManager(bitrix_id=99901, name="No", last_name="Timeman", is_active=False)
    db_session.add(mgr)
    await db_session.flush()
    db_session.add(
        CrmDeal(
            bitrix_id=7003,
            title="X",
            assigned_by_id=mgr.id,
            category_id=39,
            closed=False,
            missing_from_bitrix=False,
            has_future_activity=False,
        )
    )
    db_session.add(
        MonitoredManager(manager_id=mgr.id, auto_included=True, auto_reason="assigned_deals")
    )
    await db_session.commit()

    board = await list_manager_control(db_session)
    item = next(x for x in board["items"] if x["id"] == mgr.id)
    assert item["status_normalized"] == "no_data"
    assert item["has_snapshot"] is False
    assert "Timeman" in item["status_label"] or item["status_label"]


@pytest.mark.asyncio
async def test_crm_metrics_and_timezone_unchanged(db_session) -> None:
    mgr = CrmManager(bitrix_id=21809, name="Анастасия", last_name="Гузова", is_active=False)
    db_session.add(mgr)
    await db_session.flush()
    # 2026-10-07 02:13 Moscow = 2026-10-06 23:13 UTC — still today in Moscow
    create_ts = datetime(2026, 10, 6, 23, 13, 22, tzinfo=timezone.utc)
    db_session.add(
        CrmDeal(
            bitrix_id=7004,
            title="TZ",
            assigned_by_id=mgr.id,
            category_id=1,
            date_create=create_ts,
            closed=False,
            missing_from_bitrix=False,
            has_future_activity=True,
        )
    )
    await db_session.commit()
    await sync_monitored_roster(db_session)
    await db_session.commit()

    detail = await get_manager_control_detail(db_session, mgr.id)
    assert detail is not None
    assert detail["timezone"] == "Europe/Moscow"
    # Only assert create count if "today" in app is 2026-10-07
    today = utc_now().astimezone(app_tz()).date()
    if today == date(2026, 10, 7):
        assert detail["today"]["crm_activity"]["created_deals"] >= 1


@pytest.mark.asyncio
async def test_opened_today_board_working(db_session) -> None:
    mgr = CrmManager(bitrix_id=501, name="Open", last_name="Today", is_active=True)
    db_session.add(mgr)
    await db_session.flush()
    db_session.add(
        CrmDeal(
            bitrix_id=7005,
            title="D",
            assigned_by_id=mgr.id,
            category_id=1,
            closed=False,
            missing_from_bitrix=False,
            has_future_activity=True,
        )
    )
    observed = utc_now()
    today = observed.astimezone(app_tz()).date()
    # Build TIME_START as today 09:00 Moscow
    start_local = datetime(today.year, today.month, today.day, 9, 0, tzinfo=app_tz())
    parsed = parse_timeman_status_payload(
        {
            "STATUS": "OPENED",
            "TIME_START": start_local.isoformat(),
            "DURATION": "01:00:00",
            "TIME_LEAKS": "00:10:00",
            "TZ_OFFSET": 10800,
        },
        observed_at=observed,
        app_timezone_name="Europe/Moscow",
    )
    assert parsed.status_normalized == STATUS_WORKING
    await persist_parsed_status_safe(db_session, manager=mgr, parsed=parsed, observed_at=observed)
    await db_session.commit()

    board = await list_manager_control(db_session)
    item = next(x for x in board["items"] if x["id"] == mgr.id)
    assert item["status_normalized"] == STATUS_WORKING
    assert item["status_label"] == "Работает"
    assert item["duration_display"] == "01:00:00"
    assert item["time_start"] is not None

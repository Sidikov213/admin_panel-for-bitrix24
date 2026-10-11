"""Manager Control V1 — Timeman parse, aggregation, CRM metrics, sync isolation."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.timezone import app_tz, utc_now
from app.models.crm import CrmActivity, CrmDeal, CrmManager, DealChangeEvent
from app.models.manager_control import ManagerWorkday, ManagerWorkdaySnapshot
from app.services.manager_control_service import get_manager_control_detail, list_manager_control
from app.services.timeman_collector import (
    TimemanCollector,
    persist_parsed_status_safe,
    run_timeman_collect_safe,
)
from app.services.timeman_parse import (
    STATUS_CLOSED,
    STATUS_NOT_STARTED,
    STATUS_PAUSED,
    STATUS_STALE_UNCLOSED,
    STATUS_WORKING,
    format_seconds,
    normalize_timeman_status,
    parse_hms_to_seconds,
    parse_timeman_status_payload,
)


def test_parse_duration_and_breaks() -> None:
    assert parse_hms_to_seconds("01:30:05") == 3600 + 1800 + 5
    assert parse_hms_to_seconds("00:00:00") == 0
    assert parse_hms_to_seconds(None) is None
    assert format_seconds(3661) == "01:01:01"


def test_working_status() -> None:
    now = utc_now()
    today = now.astimezone(app_tz()).date()
    assert normalize_timeman_status("OPENED", time_start=now, today=today) == STATUS_WORKING
    assert normalize_timeman_status("PAUSED", time_start=now, today=today) == STATUS_PAUSED
    old = now - timedelta(days=120)
    assert normalize_timeman_status("EXPIRED", time_start=old, today=today) == STATUS_STALE_UNCLOSED


def test_closed_workday() -> None:
    now = utc_now()
    today = now.astimezone(app_tz()).date()
    start = datetime(today.year, today.month, today.day, 6, 0, tzinfo=timezone.utc)
    assert normalize_timeman_status("CLOSED", time_start=start, today=today) == STATUS_CLOSED


def test_not_started() -> None:
    assert normalize_timeman_status("CLOSED", time_start=None) == STATUS_NOT_STARTED


def test_timezone_and_work_date() -> None:
    observed = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    parsed = parse_timeman_status_payload(
        {
            "STATUS": "OPENED",
            "TIME_START": "2026-10-07T06:00:00+03:00",
            "TIME_FINISH": None,
            "DURATION": "02:00:00",
            "TIME_LEAKS": "00:15:00",
            "TZ_OFFSET": 10800,
        },
        observed_at=observed,
        app_timezone_name="Europe/Moscow",
    )
    assert parsed.status_normalized == STATUS_WORKING
    assert parsed.duration_seconds == 7200
    assert parsed.time_leaks_seconds == 900
    assert parsed.work_date == date(2026, 10, 7)
    assert parsed.tz_offset_seconds == 10800
    assert parsed.has_bitrix_timestamps is True
    assert "Europe/Moscow" in (parsed.source_timezone or "")


@pytest.mark.asyncio
async def test_duplicate_snapshot_prevention(db_session) -> None:
    mgr = CrmManager(bitrix_id=101, name="A", last_name="Test", is_active=True)
    db_session.add(mgr)
    await db_session.flush()

    observed = utc_now()
    today = observed.astimezone(app_tz()).date()
    start_local = datetime(today.year, today.month, today.day, 9, 0, tzinfo=app_tz())
    payload = {
        "STATUS": "OPENED",
        "TIME_START": start_local.isoformat(),
        "DURATION": "01:00:00",
        "TIME_LEAKS": "00:00:00",
        "TZ_OFFSET": 10800,
    }
    parsed = parse_timeman_status_payload(
        payload, observed_at=observed, app_timezone_name="Europe/Moscow"
    )
    inserted1, deduped1 = await persist_parsed_status_safe(
        db_session, manager=mgr, parsed=parsed, observed_at=observed
    )
    await db_session.commit()
    assert inserted1 is True and deduped1 is False

    inserted2, deduped2 = await persist_parsed_status_safe(
        db_session, manager=mgr, parsed=parsed, observed_at=observed + timedelta(minutes=5)
    )
    await db_session.commit()
    assert inserted2 is False and deduped2 is True

    snaps = (
        await db_session.execute(
            select(ManagerWorkdaySnapshot).where(ManagerWorkdaySnapshot.manager_id == mgr.id)
        )
    ).scalars().all()
    assert len(snaps) == 1

    days = (
        await db_session.execute(
            select(ManagerWorkday).where(ManagerWorkday.manager_id == mgr.id)
        )
    ).scalars().all()
    assert len(days) == 1
    assert days[0].status_normalized == STATUS_WORKING


@pytest.mark.asyncio
async def test_day_aggregation_updates(db_session) -> None:
    mgr = CrmManager(bitrix_id=102, name="B", last_name="Agg", is_active=True)
    db_session.add(mgr)
    await db_session.flush()
    observed = utc_now()
    today = observed.astimezone(app_tz()).date()
    start_s = datetime(today.year, today.month, today.day, 9, 0, tzinfo=app_tz()).isoformat()
    finish_s = datetime(today.year, today.month, today.day, 18, 0, tzinfo=app_tz()).isoformat()

    p1 = parse_timeman_status_payload(
        {
            "STATUS": "OPENED",
            "TIME_START": start_s,
            "DURATION": "01:00:00",
            "TIME_LEAKS": "00:00:00",
        },
        observed_at=observed,
        app_timezone_name="Europe/Moscow",
    )
    await persist_parsed_status_safe(db_session, manager=mgr, parsed=p1, observed_at=observed)
    await db_session.commit()

    p2 = parse_timeman_status_payload(
        {
            "STATUS": "CLOSED",
            "TIME_START": start_s,
            "TIME_FINISH": finish_s,
            "DURATION": "08:00:00",
            "TIME_LEAKS": "00:30:00",
        },
        observed_at=observed + timedelta(hours=9),
        app_timezone_name="Europe/Moscow",
    )
    await persist_parsed_status_safe(
        db_session, manager=mgr, parsed=p2, observed_at=observed + timedelta(hours=9)
    )
    await db_session.commit()

    wd = (
        await db_session.execute(
            select(ManagerWorkday).where(ManagerWorkday.manager_id == mgr.id)
        )
    ).scalar_one()
    assert wd.status_normalized == STATUS_CLOSED
    assert wd.duration_seconds == 8 * 3600
    assert wd.time_leaks_seconds == 1800
    assert wd.time_finish is not None
    assert wd.snapshot_count == 2


@pytest.mark.asyncio
async def test_missing_historical_data_week(db_session) -> None:
    mgr = CrmManager(bitrix_id=103, name="C", last_name="Hist", is_active=True)
    db_session.add(mgr)
    await db_session.flush()

    from app.repositories.sync import SyncRepository

    repo = SyncRepository(db_session)
    today = utc_now().astimezone(app_tz()).date()
    await repo.set_state(
        "timeman_history_since",
        {"at": utc_now().isoformat(), "local_date": today.isoformat()},
    )
    await db_session.commit()

    detail = await get_manager_control_detail(db_session, mgr.id)
    assert detail is not None
    # Days before history_since should not show fake zero workdays
    before = [r for r in detail["week"] if r["date"] < today.isoformat()]
    for row in before:
        assert row["workday_available"] is False
        assert row["show_as_zero_workday"] is False
        assert row.get("duration_display") is None


@pytest.mark.asyncio
async def test_manager_crm_metrics(db_session) -> None:
    mgr = CrmManager(bitrix_id=200, name="D", last_name="Crm", is_active=True)
    db_session.add(mgr)
    await db_session.flush()

    now = utc_now()
    deal = CrmDeal(
        bitrix_id=5001,
        title="T",
        assigned_by_id=mgr.id,
        category_id=1,
        date_create=now,
        closed=False,
        has_future_activity=False,
        missing_from_bitrix=False,
    )
    db_session.add(deal)
    await db_session.flush()
    db_session.add(
        DealChangeEvent(
            deal_id=deal.id,
            field_name="stage_id",
            old_value="NEW",
            new_value="IN_WORK",
            observed_at=now,
        )
    )
    db_session.add(
        CrmActivity(
            bitrix_id=9001,
            responsible_id=mgr.bitrix_id,
            owner_id=deal.bitrix_id,
            completed=True,
            completed_at=now,
            deadline=now - timedelta(days=1),
        )
    )
    db_session.add(
        CrmActivity(
            bitrix_id=9002,
            responsible_id=mgr.bitrix_id,
            owner_id=deal.bitrix_id,
            completed=False,
            deadline=now - timedelta(hours=1),
        )
    )
    await db_session.commit()

    # Need workday? list filters relevant managers with deals in category
    data = await list_manager_control(db_session)
    item = next((x for x in data["items"] if x["id"] == mgr.id), None)
    assert item is not None
    assert item["crm_actions_today"] >= 1
    assert item["overdue_activities"] >= 1
    assert item["no_future_activity"] >= 1

    detail = await get_manager_control_detail(db_session, mgr.id)
    assert detail["today"]["crm_activity"]["created_deals"] >= 1
    assert detail["today"]["crm_activity"]["completed_activities"] >= 1
    assert detail["today"]["crm_activity"]["stage_changes"] >= 1
    assert detail["today"]["crm_activity"]["overdue_activities"] >= 1


@pytest.mark.asyncio
async def test_collector_failure_isolation(db_session) -> None:
    """Timeman failure must not raise into CRM path (safe wrapper)."""
    with patch("app.db.session.async_session_factory", side_effect=RuntimeError("db_down")):
        result = await run_timeman_collect_safe()
        assert result["ok"] is False
        assert "error_message" in result


@pytest.mark.asyncio
async def test_collector_with_mock_client(db_session) -> None:
    mgr = CrmManager(bitrix_id=301, name="E", last_name="Poll", is_active=True)
    db_session.add(mgr)
    await db_session.flush()
    db_session.add(
        CrmDeal(
            bitrix_id=6001,
            title="Deal",
            assigned_by_id=mgr.id,
            category_id=1,
            closed=False,
            missing_from_bitrix=False,
            has_future_activity=True,
        )
    )
    await db_session.commit()

    client = MagicMock()
    client.webhook_configured = True
    client.timeman_status = AsyncMock(
        return_value={
            "STATUS": "OPENED",
            "TIME_START": "2026-10-07T10:00:00+03:00",
            "DURATION": "00:45:00",
            "TIME_LEAKS": "00:05:00",
            "TZ_OFFSET": 10800,
        }
    )
    with patch.dict(os.environ, {"BITRIX_WEBHOOK_URL": "https://example.test/rest/1/x/"}):
        get_settings.cache_clear()
        try:
            collector = TimemanCollector(db_session, client=client)
            result = await collector.run_cycle()
            assert result.managers_considered >= 1
            assert result.snapshots_inserted >= 1
            assert result.errors == 0

            result2 = await collector.run_cycle()
            assert result2.snapshots_deduped >= 1 or result2.snapshots_inserted == 0
        finally:
            get_settings.cache_clear()

"""Regressions for the October product audit. No external API calls."""
import logging
import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.engine import make_url

from app.api.manager_control import ScheduleIn, CalendarIn, AbsenceIn
from app.core.logging import JSONFormatter
from app.core.timezone import utc_now
from app.db.locks import AdvisoryLock
from app.models.crm import CrmActivity, CrmDeal, CrmManager, DealSnapshot
from app.models.manager_control import ManagerWorkdaySnapshot, MonitoredManager
from app.models.work_schedules import ManagerControlPolicy, ScheduleAssignment, WorkdayViolation
from app.repositories.sync import SyncRepository
from app.services.sync_service import SyncOrchestrator
from app.services.schedule_service import create_schedule, resolve_day_plan_for_manager
from app.services.violation_evaluator import evaluate_manager_day
from app.services.monitored_roster import list_monitored_managers
from app.services.timeman_collector import list_relevant_managers
from app.services.mc_reports import week_report, month_report, team_report


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def repair_db(request, db_session):
    if request.param == "sqlite":
        yield db_session
        return
    url = os.environ.get("FOCUS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set FOCUS_TEST_POSTGRES_URL to an isolated migrated audit database")
    parsed = make_url(url)
    assert parsed.host in {"localhost", "127.0.0.1"} and parsed.database.startswith("focus_audit_")
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_snapshot_reversion_keeps_latest_and_retry_dedup(repair_db):
    orch = SyncOrchestrator(repair_db, client=object())
    a = {"ID": "123", "TITLE": "A", "CATEGORY_ID": "1"}
    for raw in (a, {**a, "TITLE": "B"}, a, a):
        await orch._upsert_deal(raw)
    snapshots = list((await repair_db.execute(select(DealSnapshot).order_by(DealSnapshot.id))).scalars())
    assert [s.payload["TITLE"] for s in snapshots] == ["A", "B", "A"]


@pytest.mark.asyncio
async def test_empty_activity_delta_refresh_and_full_reconcile(repair_db):
    deal = CrmDeal(bitrix_id=10, category_id=1, has_future_activity=True)
    repair_db.add_all([deal, CrmActivity(bitrix_id=1, owner_id=10, owner_type_id=2,
        deadline=utc_now() - timedelta(hours=1), completed=False)])
    await repair_db.commit()
    client = AsyncMock()
    client.crm_activity_list.return_value = []
    orch = SyncOrchestrator(repair_db, client=client)
    assert await orch.run_activities(full=False)
    assert not deal.has_future_activity and deal.open_activities_count == 1
    assert await orch.run_activities(full=True)
    assert deal.open_activities_count == 0 and deal.next_deadline_at is None
    assert (await repair_db.scalar(select(func.count()).select_from(CrmActivity))) == 0


@pytest.mark.asyncio
async def test_bad_activity_does_not_abort_good_records_or_advance_cursor(repair_db):
    repair_db.add(CrmDeal(bitrix_id=10, category_id=1))
    await repair_db.commit()
    repo = SyncRepository(repair_db)
    await repo.set_state("last_activities_sync", {"at": "2020-01-01T00:00:00+00:00"})
    await repair_db.commit()
    client = AsyncMock()
    raw = {"ID": "1", "OWNER_ID": "10", "OWNER_TYPE_ID": "2", "SUBJECT": "ok"}
    bad = {**raw, "ID": "2", "SUBJECT": "x" * 600} if repair_db.get_bind().dialect.name == "postgresql" else {**raw, "ID": "bad"}
    client.crm_activity_list.return_value = [bad, raw]
    assert not await SyncOrchestrator(repair_db, client=client).run_activities(full=True)
    assert (await repair_db.scalar(select(func.count()).select_from(CrmActivity))) == 1
    assert (await repo.get_state("last_activities_sync"))["at"].startswith("2020-")


@pytest.mark.asyncio
async def test_watermark_is_start_of_pull_with_timezone(repair_db):
    client = AsyncMock()
    begin = utc_now()
    async def fetch(**filters):
        return []
    client.crm_deal_list.side_effect = fetch
    assert await SyncOrchestrator(repair_db, client=client).run_deals()
    from datetime import datetime
    stamp = datetime.fromisoformat((await SyncRepository(repair_db).get_state("last_deals_sync"))["at"])
    assert begin <= stamp <= utc_now()
    assert stamp.tzinfo is not None


@pytest.mark.asyncio
async def test_read_models_do_not_create_roster_or_policy(repair_db):
    mgr = CrmManager(bitrix_id=1, name="Test")
    repair_db.add(mgr)
    await repair_db.flush()
    repair_db.add(CrmDeal(bitrix_id=1, category_id=1, assigned_by_id=mgr.id))
    await repair_db.commit()
    from app.services.manager_control_service import list_manager_control
    assert [m.id for m in await list_monitored_managers(repair_db)] == [mgr.id]
    await list_manager_control(repair_db)
    await repair_db.commit()
    for model in (MonitoredManager, ManagerControlPolicy):
        assert (await repair_db.scalar(select(func.count()).select_from(model))) == 0


@pytest.mark.asyncio
async def test_all_managers_receive_poll_slots(repair_db):
    for i in range(55):
        mgr = CrmManager(bitrix_id=i+1)
        repair_db.add(mgr)
        await repair_db.flush()
        repair_db.add(MonitoredManager(manager_id=mgr.id, manual_include=True))
    await repair_db.commit()
    first = await list_relevant_managers(repair_db, limit=50)
    await SyncRepository(repair_db).set_state("timeman_roster_cursor", {"manager_id": first[-1].id})
    second = await list_relevant_managers(repair_db, limit=50)
    assert len({m.id for m in first + second}) == 55


@pytest.mark.asyncio
async def test_department_schedule_and_no_cross_day_violations(repair_db):
    mgr = CrmManager(bitrix_id=1, raw={"UF_DEPARTMENT": [7]})
    repair_db.add(mgr)
    await repair_db.flush()
    schedule = await create_schedule(repair_db, {"name": "Test", "weekdays": [1,2,3,4,5], "start_time": "09:00", "end_time": "18:00"})
    repair_db.add(ScheduleAssignment(schedule_id=schedule.id, department_key="7"))
    now = datetime(2026,10,28,9,tzinfo=timezone.utc)
    repair_db.add(ManagerWorkdaySnapshot(manager_id=mgr.id, bitrix_user_id=1,
        work_date=date(2026,10,28), observed_at=now, status_raw="OPENED", status_normalized="working",
        time_start=now, duration_seconds=3600, content_hash="a"*64))
    await repair_db.commit()
    assert (await resolve_day_plan_for_manager(repair_db, mgr.id, now.date()))[0].id == schedule.id
    result = await evaluate_manager_day(repair_db, mgr.id, date(2026,10,27), now=now)
    assert result["coverage"] == "unknown" and result["candidates"] == 0
    assert (await repair_db.scalar(select(func.count()).select_from(WorkdayViolation))) == 0


@pytest.mark.asyncio
async def test_reports_no_data_is_not_zero_and_preview_is_not_official(repair_db):
    mgr = CrmManager(bitrix_id=1)
    repair_db.add(mgr)
    await repair_db.flush()
    repair_db.add(MonitoredManager(manager_id=mgr.id, manual_include=True))
    day = utc_now().date()
    repair_db.add(WorkdayViolation(manager_id=mgr.id, work_date=day, violation_type="LATE_START",
        detected_at=utc_now(), state="OPEN", severity="WARNING", is_preview=True))
    await repair_db.commit()
    week = await week_report(repair_db, mgr.id, anchor=day)
    month = await month_report(repair_db, mgr.id, year=day.year, month=day.month)
    team = await team_report(repair_db, start=day, end=day)
    for row in (week["totals"], month, team["items"][0]):
        assert row["fact_seconds"] is None and row["delta_minutes"] is None
    assert week["totals"]["open_violations"] == month["total_open_violations"] == team["items"][0]["open_violations"] == 0


@pytest.mark.asyncio
async def test_lock_survives_session_commit_and_releases(repair_db):
    lock = AdvisoryLock(repair_db, 19283746)
    assert await lock.acquire()
    await repair_db.commit()
    if repair_db.get_bind().dialect.name == "postgresql":
        other = AdvisoryLock(repair_db, 19283746)
        assert not await other.acquire()
        await lock.release()
        assert await other.acquire()
        await other.release()
    else:
        await lock.release()


@pytest.mark.asyncio
async def test_freshness_requires_all_phases(repair_db):
    repo = SyncRepository(repair_db)
    for key in ("last_deals_sync", "last_activities_sync", "last_dictionaries_sync"):
        await repo.set_state(key, {"at": (utc_now() - timedelta(days=10)).isoformat()})
    await repo.set_state("last_dictionaries_sync", {"at": utc_now().isoformat()})
    assert (await repo.crm_freshness())["is_stale"]


@pytest.mark.asyncio
async def test_worker_attempts_timeman_when_crm_raises():
    from app.workers import sync_worker as worker
    with patch.object(worker, "should_full_reconcile", AsyncMock(side_effect=RuntimeError)), \
         patch.object(worker, "_run_timeman_collect_isolated", AsyncMock()) as timeman, \
         patch.object(worker, "_run_violation_evaluation_isolated", AsyncMock()) as violations:
        await worker.scheduled_job()
        timeman.assert_awaited_once()
        violations.assert_awaited_once()


@pytest.mark.parametrize("change", [{"timezone":"Invalid/Zone"}, {"weekdays":[99]}, {"start_time":"99:99"}, {"required_minutes":-1}, {"end_time":"08:00"}])
def test_invalid_schedule_rejected(change):
    with pytest.raises(ValidationError):
        ScheduleIn(**{"name":"Test", "start_time":"09:00", "end_time":"18:00", **change})


def test_calendar_and_absence_validation():
    with pytest.raises(ValidationError):
        CalendarIn(day_date="2026-10-28", kind="shortened")
    with pytest.raises(ValidationError):
        AbsenceIn(manager_id=1, date_from="2026-10-28", date_to="2026-10-01")


def test_log_secrets_redacted():
    record = logging.LogRecord("test", logging.ERROR, __file__, 1,
        "Authorization: Bearer abc123 https://x.bitrix24.ru/rest/1/token123/ password=bad123", (), None)
    output = JSONFormatter().format(record)
    assert all(secret not in output for secret in ("abc123", "token123", "bad123"))


@pytest.mark.parametrize("change", [{"COOKIE_SECURE":False}, {"DEMO_MODE":True}, {"CORS_ORIGINS":"*"}, {"DATABASE_URL":"postgresql+asyncpg://postgres:postgres@localhost/test"}])
def test_unsafe_production_settings_rejected(change):
    from app.core.config import Settings
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{"APP_ENV":"production", "COOKIE_SECURE":True, "DEMO_MODE":False,
            "CORS_ORIGINS":"https://analytics.example.com", "DATABASE_URL":"postgresql+asyncpg://test:synthetic-test-password@localhost/test", **change})


@pytest.mark.asyncio
async def test_invalid_upstream_list_cannot_look_like_empty_success():
    from app.integrations.bitrix.client import BitrixClient, BitrixClientError
    client = BitrixClient()
    client.call = AsyncMock(return_value={"unexpected": []})
    with pytest.raises(BitrixClientError):
        await client.crm_deal_list()


@pytest.mark.asyncio
async def test_failed_activity_phase_marks_whole_cycle_failed():
    from app.workers import sync_worker as worker
    from types import SimpleNamespace
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def session():
        yield object()
    with patch.object(worker, "get_settings", return_value=SimpleNamespace(BITRIX_WEBHOOK_URL="synthetic")), \
         patch.object(worker, "async_session_factory", session), \
         patch.object(worker.SyncOrchestrator, "__init__", return_value=None), \
         patch.object(worker.SyncOrchestrator, "run_dictionaries", AsyncMock(return_value=True)), \
         patch.object(worker.SyncOrchestrator, "run_deals", AsyncMock(return_value=True)), \
         patch.object(worker.SyncOrchestrator, "run_activities", AsyncMock(return_value=False)):
        assert not await worker.run_sync_cycle(full_reconcile=True)


@pytest.mark.asyncio
async def test_team_report_query_budget_with_55_managers(db_session):
    from sqlalchemy import event
    for i in range(55):
        mgr = CrmManager(bitrix_id=i+1)
        db_session.add(mgr)
        await db_session.flush()
        db_session.add(MonitoredManager(manager_id=mgr.id, manual_include=True))
    await create_schedule(db_session, {"name":"Test", "weekdays":[1,2,3,4,5], "start_time":"09:00", "end_time":"18:00", "is_default":True, "required_minutes":480})
    await db_session.commit()
    count = 0
    def query(*args):
        nonlocal count
        count += 1
    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", query)
    try:
        report = await team_report(db_session, start=date(2026,10,1), end=date(2026,10,28))
    finally:
        event.remove(engine, "before_cursor_execute", query)
    assert report["total"] == 55
    assert count < 300, count

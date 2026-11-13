"""Regressions from the live stand: the worker hung on pagination and nobody noticed."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password
from app.core.config import get_settings
from app.integrations.bitrix.client import BitrixClient
from app.models.auth import User, UserRole
from app.models.sync import SyncRun, SyncStatus, SyncType
from app.repositories.sync import SyncRepository
from app.services.sync_service import SyncOrchestrator
from app.services.system_service import SystemService
from app.workers.sync_worker import full_reconcile_due, missed_reports

MSK = timezone(timedelta(hours=3))


def _bitrix(monkeypatch, pages_for_start):
    """Fake portal. Like the real one, a `start` past the end returns the last page again."""
    calls: list[int] = []

    async def fake_post(self, url, json=None, **kwargs):
        start = (json or {}).get("start", 0)
        calls.append(start)
        if len(calls) > 20:
            raise AssertionError("pagination does not stop")
        return httpx.Response(200, json=pages_for_start(start), request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return calls


@pytest.mark.asyncio
async def test_last_page_of_exactly_50_rows_does_not_loop(monkeypatch) -> None:
    page = [{"ID": str(i)} for i in range(1, 51)]
    # 50 rows in total: no `next`, and every later `start` gets the same page back
    calls = _bitrix(monkeypatch, lambda start: {"result": page, "total": 50})
    client = BitrixClient(webhook_url="https://example.bitrix24.ru/rest/1/xxx/", rate_limit_rps=0)
    items = await client.call_paginated("crm.activity.list", {})
    assert len(items) == 50
    assert calls == [0]


@pytest.mark.asyncio
async def test_repeated_page_stops_pagination_without_total(monkeypatch) -> None:
    page = [{"ID": str(i)} for i in range(1, 51)]
    calls = _bitrix(monkeypatch, lambda start: {"result": page})
    client = BitrixClient(webhook_url="https://example.bitrix24.ru/rest/1/xxx/", rate_limit_rps=0)
    items = await client.call_paginated("crm.activity.list", {})
    assert len(items) == 50
    assert calls == [0, 50]


@pytest.mark.asyncio
async def test_pagination_follows_next_to_the_end(monkeypatch) -> None:
    def pages(start):
        if start == 0:
            return {"result": [{"ID": str(i)} for i in range(1, 51)], "next": 50, "total": 100}
        return {"result": [{"ID": str(i)} for i in range(51, 101)], "total": 100}

    calls = _bitrix(monkeypatch, pages)
    client = BitrixClient(webhook_url="https://example.bitrix24.ru/rest/1/xxx/", rate_limit_rps=0)
    items = await client.call_paginated("crm.deal.list", {})
    assert [i["ID"] for i in items] == [str(i) for i in range(1, 101)]
    assert calls == [0, 50]


@pytest.mark.asyncio
async def test_sync_filter_carries_utc_offset(db_session: AsyncSession) -> None:
    orch = SyncOrchestrator(db_session, client=AsyncMock())
    overlap = get_settings().SYNC_OVERLAP_MINUTES
    value = orch._since_filter("2026-11-05T17:16:21.988238+00:00")
    assert value.endswith("+00:00")
    assert datetime.fromisoformat(value) == datetime(2026, 11, 5, 17, 16, 21, tzinfo=timezone.utc) - timedelta(minutes=overlap)


def test_full_reconcile_waits_for_the_night_window() -> None:
    last = datetime(2026, 11, 12, 4, 0, tzinfo=MSK)
    assert full_reconcile_due(None, last) is True
    # Not due yet
    assert full_reconcile_due(last, last + timedelta(hours=23)) is False
    # Due, but it is the working day: keep the 5-minute sync going
    assert full_reconcile_due(last, datetime(2026, 11, 13, 11, 0, tzinfo=MSK)) is False
    # Due and inside the quiet window
    assert full_reconcile_due(last, datetime(2026, 11, 14, 1, 0, tzinfo=MSK)) is True
    # The machine was off at night: after two intervals it runs at the first chance
    assert full_reconcile_due(last, datetime(2026, 11, 14, 11, 0, tzinfo=MSK)) is True


def test_missed_reports_within_catch_up_window() -> None:
    # 2026-11-13 is a Friday, 2026-11-16 a Monday, 2026-11-14 a Saturday
    assert missed_reports(datetime(2026, 11, 13, 19, 59, tzinfo=MSK)) == []
    assert missed_reports(datetime(2026, 11, 13, 20, 30, tzinfo=MSK)) == ["daily"]
    assert missed_reports(datetime(2026, 11, 13, 23, 30, tzinfo=MSK)) == []
    assert missed_reports(datetime(2026, 11, 16, 9, 10, tzinfo=MSK)) == ["weekly"]
    assert missed_reports(datetime(2026, 11, 14, 20, 30, tzinfo=MSK)) == []


@pytest.mark.asyncio
async def test_runs_left_running_are_closed(db_session: AsyncSession) -> None:
    repo = SyncRepository(db_session)
    stuck = await repo.start_run(SyncType.activities)
    done = await repo.start_run(SyncType.deals)
    await repo.finish_run(done, status=SyncStatus.success, items_processed=3, errors_count=0)
    await db_session.commit()

    assert await SyncOrchestrator(db_session, client=AsyncMock()).close_stale_runs() == 1
    await db_session.refresh(stuck)
    await db_session.refresh(done)
    assert stuck.status == SyncStatus.failed and stuck.finished_at is not None and stuck.error_message
    assert done.status == SyncStatus.success


@pytest.mark.asyncio
async def test_system_status_reports_stopped_sync(client: AsyncClient, db_session: AsyncSession, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "BITRIX_WEBHOOK_URL", "https://example.bitrix24.ru/rest/1/xxx/")
    monkeypatch.setattr(SystemService, "_cached_bitrix_ping", AsyncMock(return_value=True))
    db_session.add(User(email="stale@example.com", password_hash=hash_password("password123"), role=UserRole.viewer))
    repo = SyncRepository(db_session)
    # The worker died mid-run a week ago: Bitrix answers, no run failed, the row still says «running»
    await repo.start_run(SyncType.activities)
    await repo.set_state("last_deals_sync", {"at": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()})
    await db_session.commit()
    assert (await client.post("/api/v1/auth/login", json={"email": "stale@example.com", "password": "password123"})).status_code == 200

    body = (await client.get("/api/v1/system")).json()
    assert body["bitrix_reachable"] is True
    assert body["sync_stalled"] is True and body["data_may_be_stale"] is True
    assert "8 дн." in body["stale_note"]

    await repo.set_state("last_deals_sync", {"at": datetime.now(timezone.utc).isoformat()})
    await db_session.commit()
    body = (await client.get("/api/v1/system")).json()
    assert body["sync_stalled"] is False and body["data_may_be_stale"] is False and body["stale_note"] is None

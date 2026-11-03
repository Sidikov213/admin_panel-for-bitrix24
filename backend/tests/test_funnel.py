"""Funnel analytics, stage history sync and Bitrix stagehistory client."""

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.funnel import compute_funnel
from app.auth.password import hash_password
from app.integrations.bitrix.client import BitrixClient, BitrixClientError
from app.models.auth import User, UserRole
from app.models.crm import CrmDeal, CrmManager, CrmPipeline, CrmStage, DealChangeEvent, DealStageHistory
from app.models.sync import SyncRun, SyncStatus, SyncType
from app.repositories.sync import SyncRepository
from app.services.sync_service import STAGE_HISTORY_STATE, SyncOrchestrator

OCT = (date(2026, 10, 1), date(2026, 10, 31))


def at(month: int, day: int) -> datetime:
    return datetime(2026, month, day, 12, tzinfo=timezone.utc)


async def _seed(session: AsyncSession) -> dict:
    pipe = CrmPipeline(bitrix_id=1, name="Сваи", sort=0)
    session.add(pipe)
    await session.flush()
    stages = {
        code: CrmStage(bitrix_id=f"C1:{code}", pipeline_id=pipe.id, name=name, sort=sort, semantics=sem)
        for code, name, sort, sem in [
            ("NEW", "Новая", 10, "process"),
            ("QUAL", "Квалификация", 20, "process"),
            ("PROP", "КП", 30, None),  # unknown semantics counts as an in-progress stage
            ("WON", "Успешно", 40, "success"),
            ("LOSE", "Провал", 50, "failure"),
        ]
    }
    ivan = CrmManager(bitrix_id=7, name="Иван", last_name="Петров")
    olga = CrmManager(bitrix_id=8, name="Ольга", last_name="Смирнова")
    session.add_all([*stages.values(), ivan, olga])
    await session.flush()

    def deal(bid, mgr, created, stage, *, closed=False, closedate=None, amount=None):
        return CrmDeal(
            bitrix_id=bid, title=f"d{bid}", category_id=1, assigned_by_id=mgr.id, stage_id=stages[stage].id,
            date_create=created, closed=closed, closedate=closedate,
            opportunity=Decimal(amount) if amount else None,
        )

    deals = [
        deal(1, ivan, at(10, 1), "WON", closed=True, closedate=at(10, 18), amount="100000"),
        deal(2, ivan, at(10, 2), "LOSE", closed=True, closedate=at(10, 10)),
        deal(3, ivan, at(10, 5), "NEW"),
        deal(4, olga, at(10, 6), "PROP"),
        deal(5, olga, at(10, 9), "PROP"),
        # Created before the period, won inside it: counts for win rate and cycle, not the cohort
        deal(6, olga, at(9, 20), "WON", closed=True, closedate=at(10, 20), amount="50000"),
        # Other pipeline: ignored
        CrmDeal(bitrix_id=99, title="x", category_id=39, date_create=at(10, 3), closed=False),
    ]
    session.add_all(deals)
    await session.flush()

    hid = 0
    for bid, moves in {
        1: [("NEW", at(10, 1)), ("QUAL", at(10, 3)), ("PROP", at(10, 8)), ("WON", at(10, 18))],
        2: [("NEW", at(10, 2)), ("QUAL", at(10, 4)), ("LOSE", at(10, 10))],
        3: [("NEW", at(10, 5))],
        4: [("NEW", at(10, 6)), ("PROP", at(10, 7))],  # skipped QUAL
    }.items():
        for code, ts in moves:
            hid += 1
            session.add(DealStageHistory(bitrix_id=hid, deal_bitrix_id=bid, stage_bitrix_id=f"C1:{code}",
                                         category_id=1, created_time=ts))
    # Deal 5: no Bitrix history, one stage change observed by polling
    session.add(DealChangeEvent(deal_id=deals[4].id, field_name="stage_id", old_value=str(stages["QUAL"].id),
                                new_value=str(stages["PROP"].id), observed_at=at(10, 12)))
    await session.commit()
    return {"ivan": ivan, "olga": olga}


@pytest.mark.asyncio
async def test_funnel_conversion(db_session: AsyncSession) -> None:
    await _seed(db_session)
    r = await compute_funnel(db_session, category_id=1, period_start=OCT[0], period_end=OCT[1])

    steps = {s["name"]: s for s in r["funnel"]}
    assert [s["name"] for s in r["funnel"]] == ["Новая", "Квалификация", "КП", "Успешно"]
    assert [s["reached"] for s in r["funnel"]] == [5, 4, 3, 1]
    assert steps["КП"]["conversion_from_prev"] == 75.0
    assert steps["Успешно"]["conversion_from_prev"] == 33.3
    assert steps["Успешно"]["conversion_from_start"] == 20.0


@pytest.mark.asyncio
async def test_time_in_stage(db_session: AsyncSession) -> None:
    await _seed(db_session)
    r = await compute_funnel(db_session, category_id=1, period_start=OCT[0], period_end=OCT[1])
    t = {s["name"]: s for s in r["stage_time"]}
    assert (t["Новая"]["median_days"], t["Новая"]["count"]) == (2.0, 3)  # 2, 2, 1 days
    # QUAL: 5 and 6 days (Bitrix) + 3 days for deal 5 (created 9th in QUAL, observed move on 12th)
    assert (t["Квалификация"]["median_days"], t["Квалификация"]["count"]) == (5.0, 3)
    assert t["КП"]["median_days"] == 10.0
    assert t["Новая"]["current_count"] == 1 and t["КП"]["current_count"] == 2


@pytest.mark.asyncio
async def test_outcomes_losses_managers_quality(db_session: AsyncSession) -> None:
    seeded = await _seed(db_session)
    r = await compute_funnel(db_session, category_id=1, period_start=OCT[0], period_end=OCT[1])
    s = r["summary"]
    assert (s["created"], s["won"], s["lost"], s["win_rate"]) == (5, 2, 1, 66.7)
    assert s["won_amount"] == 150000.0 and s["avg_won_amount"] == 75000.0
    assert s["cycle_won"]["median_days"] == 23.5  # 17 and 30 days
    assert r["losses"] == [{"stage_id": "C1:QUAL", "name": "Квалификация", "count": 1, "share": 100.0}]

    by_name = {m["name"]: m for m in r["managers"]}
    assert (by_name["Петров Иван"]["created"], by_name["Петров Иван"]["win_rate"]) == (3, 50.0)
    assert (by_name["Смирнова Ольга"]["won"], by_name["Смирнова Ольга"]["win_rate"]) == (1, 100.0)

    q = r["data_quality"]
    assert q["source"] == "mixed" and q["history_coverage"] == 66.7  # 4 of 6 deals have Bitrix history

    only_ivan = await compute_funnel(
        db_session, category_id=1, period_start=OCT[0], period_end=OCT[1], manager_id=seeded["ivan"].id
    )
    assert only_ivan["summary"]["created"] == 3 and only_ivan["managers"] == []


@pytest.mark.asyncio
async def test_funnel_without_history_uses_current_stage(db_session: AsyncSession) -> None:
    await _seed(db_session)
    await db_session.execute(DealStageHistory.__table__.delete())
    await db_session.execute(DealChangeEvent.__table__.delete())
    await db_session.commit()
    r = await compute_funnel(db_session, category_id=1, period_start=OCT[0], period_end=OCT[1])
    assert [s["reached"] for s in r["funnel"]] == [5, 3, 3, 1]  # deal 2 lost: path = current LOSE only
    assert r["data_quality"]["source"] == "none" and r["data_quality"]["note"]


# --- Bitrix client -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_stagehistory_paginates_result_items(monkeypatch) -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if body["start"] == 0:
            return httpx.Response(200, json={"result": {"items": [{"ID": "1"}, {"ID": "2"}]}, "next": 2, "total": 3})
        return httpx.Response(200, json={"result": {"items": [{"ID": "3"}]}, "total": 3})

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)
    client = BitrixClient(webhook_url="https://example.bitrix24.ru/rest/1/xxx/", rate_limit_rps=1000)
    items = await client.crm_stagehistory_list(filters={"CATEGORY_ID": 1, ">ID": 0})
    assert [i["ID"] for i in items] == ["1", "2", "3"]
    assert calls[0]["entityTypeId"] == 2 and calls[0]["order"] == {"ID": "ASC"}
    assert [c["start"] for c in calls] == [0, 2]


# --- sync ----------------------------------------------------------------------------


class FakeHistoryBitrix:
    def __init__(self, rows_by_cat: dict[int, list[dict]], fail: bool = False) -> None:
        self.rows_by_cat = rows_by_cat
        self.calls: list[dict] = []
        self.fail = fail

    async def crm_stagehistory_list(self, *, filters, max_pages=None):
        self.calls.append(dict(filters))
        if self.fail:
            raise BitrixClientError("Method not found", kind="bitrix_error")
        min_id = filters.get(">ID", 0)
        return [r for r in self.rows_by_cat.get(filters["CATEGORY_ID"], []) if int(r["ID"]) > min_id]


def _row(hid: int, deal: int, stage: str, cat: int = 1) -> dict:
    return {
        "ID": str(hid), "TYPE_ID": "2", "OWNER_ID": str(deal), "CREATED_TIME": "2026-10-05T10:00:00+03:00",
        "CATEGORY_ID": str(cat), "STAGE_SEMANTIC_ID": "P", "STAGE_ID": stage,
    }


def _orch(session: AsyncSession, client) -> SyncOrchestrator:
    orch = SyncOrchestrator(session, client=client)
    orch._sync_repo.try_advisory_lock = AsyncMock(return_value=True)  # type: ignore[method-assign]
    orch._sync_repo.advisory_unlock = AsyncMock()  # type: ignore[method-assign]
    return orch


@pytest.mark.asyncio
async def test_stage_history_sync_inserts_dedupes_and_advances_cursor(db_session: AsyncSession) -> None:
    client = FakeHistoryBitrix(
        {1: [_row(10, 1, "C1:NEW"), _row(11, 1, "C1:QUAL"), {"ID": "12", "OWNER_ID": "1"}], 39: [_row(20, 5, "C39:NEW", 39)]}
    )
    await _orch(db_session, client).run_stage_history()

    rows = (await db_session.execute(select(DealStageHistory).order_by(DealStageHistory.bitrix_id))).scalars().all()
    assert [r.bitrix_id for r in rows] == [10, 11, 20]  # row without stage/time skipped
    assert rows[0].semantics == "process" and rows[0].created_time.hour == 7  # +03:00 → UTC
    assert (await SyncRepository(db_session).get_state(STAGE_HISTORY_STATE))["max_id"] == 20

    client.rows_by_cat[1].append(_row(21, 1, "C1:PROP"))
    await _orch(db_session, client).run_stage_history()
    assert client.calls[-1][">ID"] == 20
    count = (await db_session.execute(select(func.count()).select_from(DealStageHistory))).scalar_one()
    assert count == 4


@pytest.mark.asyncio
async def test_stage_history_unavailable_records_failed_run(db_session: AsyncSession) -> None:
    await _orch(db_session, FakeHistoryBitrix({}, fail=True)).run_stage_history()
    run = (
        await db_session.execute(select(SyncRun).where(SyncRun.sync_type == SyncType.stage_history))
    ).scalar_one()
    assert run.status == SyncStatus.failed and "Method not found" in (run.error_message or "")
    assert await SyncRepository(db_session).get_state(STAGE_HISTORY_STATE) is None


# --- API -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_funnel_api(client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed(db_session)
    db_session.add(User(email="v@ex.com", password_hash=hash_password("password123"), role=UserRole.viewer, is_active=True))
    await db_session.commit()
    assert (await client.get("/api/v1/funnel")).status_code == 401
    await client.post("/api/v1/auth/login", json={"email": "v@ex.com", "password": "password123"})

    r = await client.get("/api/v1/funnel", params={"period_start": "2026-10-01", "period_end": "2026-10-31"})
    assert r.status_code == 200
    body = r.json()
    assert body["pipeline"]["name"] == "Сваи"  # default = first configured pipeline
    assert body["summary"]["win_rate"] == 66.7

    bad = await client.get("/api/v1/funnel", params={"period_start": "2026-10-31", "period_end": "2026-10-01"})
    assert bad.status_code == 422

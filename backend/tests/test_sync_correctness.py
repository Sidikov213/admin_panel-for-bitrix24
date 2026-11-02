"""Regression: time-based deal flags, deleted activities, run-start cursor, savepoints, overdue scope."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.kpi import compute_period_kpis
from app.models.crm import CrmActivity, CrmDeal, CrmManager, CrmPipeline, CrmStage
from app.models.sync import SyncRun, SyncStatus, SyncType
from app.repositories.sync import SyncRepository
from app.services.sync_service import SyncOrchestrator


class FakeBitrix:
    def __init__(self, deals: list[dict] | None = None, activities: list[dict] | None = None) -> None:
        self.deals = deals or []
        self.activities = activities or []
        self.deal_list_called_at: datetime | None = None

    async def crm_deal_list(self, **filters):
        if self.deal_list_called_at is None:
            self.deal_list_called_at = datetime.now(timezone.utc)
        cat = filters.get("CATEGORY_ID")
        return [d for d in self.deals if str(d.get("CATEGORY_ID")) == str(cat)]

    async def crm_activity_list(self, **filters):
        return self.activities


def _orchestrator(session: AsyncSession, client: FakeBitrix) -> SyncOrchestrator:
    orch = SyncOrchestrator(session, client=client)  # type: ignore[arg-type]
    orch._sync_repo.try_advisory_lock = AsyncMock(return_value=True)  # type: ignore[method-assign]
    orch._sync_repo.advisory_unlock = AsyncMock()  # type: ignore[method-assign]
    return orch


async def _seed_deal(session: AsyncSession, bitrix_id: int = 100, **kw) -> CrmDeal:
    mgr = CrmManager(bitrix_id=bitrix_id, name="A", last_name="B", is_active=True)
    session.add(mgr)
    await session.flush()
    deal = CrmDeal(
        bitrix_id=bitrix_id,
        title="d",
        category_id=1,
        assigned_by_id=mgr.id,
        closed=False,
        **kw,
    )
    session.add(deal)
    await session.commit()
    return deal


def _activity(bitrix_id: int, owner_id: int, deadline: datetime, *, owner_type: int = 2) -> CrmActivity:
    return CrmActivity(
        bitrix_id=bitrix_id,
        owner_type_id=owner_type,
        owner_id=owner_id,
        deadline=deadline,
        completed=False,
    )


@pytest.mark.asyncio
async def test_future_flag_expires_when_deadline_passes_without_changes(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    # Flag was true when the deadline was still ahead; nothing changed in Bitrix since
    deal = await _seed_deal(db_session, has_future_activity=True, open_activities_count=1)
    db_session.add(_activity(1, deal.bitrix_id, now - timedelta(hours=1)))
    await db_session.commit()

    await _orchestrator(db_session, FakeBitrix()).run_activities(full=False)

    await db_session.refresh(deal)
    assert deal.has_future_activity is False
    assert deal.open_activities_count == 1
    assert deal.next_deadline_at is not None


@pytest.mark.asyncio
async def test_full_activity_sync_deletes_activities_missing_in_bitrix(db_session: AsyncSession) -> None:
    future = datetime.now(timezone.utc) + timedelta(days=1)
    deal = await _seed_deal(db_session)
    db_session.add_all([_activity(1, deal.bitrix_id, future), _activity(2, deal.bitrix_id, future)])
    await db_session.commit()

    kept = {
        "ID": "1",
        "OWNER_TYPE_ID": "2",
        "OWNER_ID": str(deal.bitrix_id),
        "DEADLINE": future.isoformat(),
        "COMPLETED": "N",
    }
    await _orchestrator(db_session, FakeBitrix(activities=[kept])).run_activities(full=True)

    ids = set((await db_session.execute(select(CrmActivity.bitrix_id))).scalars().all())
    assert ids == {1}


@pytest.mark.asyncio
async def test_full_activity_sync_empty_response_keeps_local_data(db_session: AsyncSession) -> None:
    future = datetime.now(timezone.utc) + timedelta(days=1)
    deal = await _seed_deal(db_session)
    db_session.add(_activity(1, deal.bitrix_id, future))
    await db_session.commit()

    await _orchestrator(db_session, FakeBitrix(activities=[])).run_activities(full=True)

    ids = set((await db_session.execute(select(CrmActivity.bitrix_id))).scalars().all())
    assert ids == {1}


@pytest.mark.asyncio
async def test_deals_cursor_is_run_start_not_finish(db_session: AsyncSession) -> None:
    client = FakeBitrix(deals=[{"ID": "5", "TITLE": "x", "CATEGORY_ID": "1", "CLOSED": "N"}])
    await _orchestrator(db_session, client).run_deals(full=False)

    state = await SyncRepository(db_session).get_state("last_deals_sync")
    assert state is not None
    assert client.deal_list_called_at is not None
    # Anything modified after the Bitrix window opened must fall into the next window
    assert datetime.fromisoformat(state["at"]) <= client.deal_list_called_at


@pytest.mark.asyncio
async def test_db_error_on_one_deal_does_not_poison_the_run(db_session: AsyncSession) -> None:
    await _seed_deal(db_session, bitrix_id=10)
    client = FakeBitrix(
        deals=[
            {"ID": "1", "TITLE": "broken", "CATEGORY_ID": "1", "CLOSED": "N"},
            {"ID": "2", "TITLE": "ok", "CATEGORY_ID": "1", "CLOSED": "N"},
        ]
    )
    orch = _orchestrator(db_session, client)
    original = orch._upsert_deal

    async def upsert(raw):
        if raw["ID"] == "1":
            # Duplicate bitrix_id → IntegrityError on flush
            db_session.add(CrmDeal(bitrix_id=10, title="dup"))
            await db_session.flush()
        return await original(raw)

    orch._upsert_deal = upsert  # type: ignore[method-assign]
    await orch.run_deals(full=False)

    titles = set((await db_session.execute(select(CrmDeal.title))).scalars().all())
    assert "ok" in titles
    run = (
        await db_session.execute(select(SyncRun).where(SyncRun.sync_type == SyncType.deals))
    ).scalar_one()
    assert run.status == SyncStatus.failed
    assert run.errors_count == 1
    assert run.items_processed == 1
    # Failed upsert → cursor must not advance
    assert await SyncRepository(db_session).get_state("last_deals_sync") is None


@pytest.mark.asyncio
async def test_overdue_counts_only_activities_of_synced_deals(db_session: AsyncSession) -> None:
    past = datetime.now(timezone.utc) - timedelta(days=1)
    pipe = CrmPipeline(bitrix_id=1, name="P", sort=0)
    db_session.add(pipe)
    await db_session.flush()
    db_session.add(CrmStage(bitrix_id="NEW", pipeline_id=pipe.id, name="New", sort=0, semantics="process"))
    deal = await _seed_deal(db_session, bitrix_id=100)
    gone = await _seed_deal(db_session, bitrix_id=200, missing_from_bitrix=True)
    db_session.add_all(
        [
            _activity(1, deal.bitrix_id, past),  # counted
            _activity(2, deal.bitrix_id, past, owner_type=1),  # lead with the same numeric id
            _activity(3, gone.bitrix_id, past),  # deal missing from Bitrix
            _activity(4, 999, past),  # deal outside synced pipelines (not stored locally)
        ]
    )
    await db_session.commit()

    today = date.today()
    total = await compute_period_kpis(db_session, today, today, include_series=False)
    by_manager = await compute_period_kpis(
        db_session, today, today, manager_id=deal.assigned_by_id, include_series=False
    )
    assert total["open_overdue"] == 1
    assert by_manager["open_overdue"] == 1

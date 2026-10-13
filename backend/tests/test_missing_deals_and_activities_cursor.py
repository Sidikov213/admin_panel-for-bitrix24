"""Regression: missing deals marked on full reconcile; activities use LAST_UPDATED cursor."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm import CrmActivity, CrmDeal, CrmManager, CrmPipeline, CrmStage
from app.repositories.sync import SyncRepository
from app.services.sync_service import SyncOrchestrator


class FakeBitrix:
    def __init__(self, deals: list[dict], activities: list[dict] | None = None) -> None:
        self.deals = deals
        self.activities = activities or []
        self.activity_calls: list[dict] = []
        self.fail_activities = False

    async def crm_deal_list(self, **filters):
        cat = filters.get("CATEGORY_ID")
        return [d for d in self.deals if str(d.get("CATEGORY_ID")) == str(cat)]

    async def crm_activity_list(self, **filters):
        self.activity_calls.append(filters)
        if self.fail_activities:
            raise RuntimeError("bitrix activity list failed")
        return self.activities


# Sanitized fixture shape from live crm.activity.list (DATE_MODIFY absent).
LIVE_ACTIVITY_FIXTURE = [
    {
        "ID": "900001",
        "TYPE_ID": "2",
        "SUBJECT": "Call",
        "RESPONSIBLE_ID": "1",
        "OWNER_TYPE_ID": "2",
        "OWNER_ID": "8581",
        "CREATED": "2026-10-04T12:00:00+03:00",
        # Far-future deadlines so has_future_activity stays True regardless of wall clock
        "DEADLINE": "2099-10-10T15:00:00+03:00",
        "COMPLETED": "N",
        "LAST_UPDATED": "2026-10-05T15:41:49+03:00",
        # DATE_MODIFY intentionally absent — live portal returns null/missing
    },
    {
        "ID": "900002",
        "TYPE_ID": "2",
        "SUBJECT": "Follow-up",
        "RESPONSIBLE_ID": "1",
        "OWNER_TYPE_ID": "2",
        "OWNER_ID": "8581",
        "CREATED": "2026-10-05T10:00:00+03:00",
        "DEADLINE": "2099-10-12T12:00:00+03:00",
        "COMPLETED": "N",
        "LAST_UPDATED": "2026-10-05T15:45:09+03:00",
    },
]


@pytest.mark.asyncio
async def test_full_reconcile_marks_missing_deals(db_session: AsyncSession) -> None:
    mgr = CrmManager(bitrix_id=1, name="A", last_name="B", is_active=True)
    pipe = CrmPipeline(bitrix_id=1, name="P", sort=0)
    db_session.add_all([mgr, pipe])
    await db_session.flush()
    stage = CrmStage(bitrix_id="NEW", pipeline_id=pipe.id, name="New", sort=0, semantics="process")
    db_session.add(stage)
    await db_session.flush()
    keep = CrmDeal(
        bitrix_id=10,
        title="keep",
        category_id=1,
        stage_id=stage.id,
        assigned_by_id=mgr.id,
        closed=False,
        missing_from_bitrix=False,
    )
    gone = CrmDeal(
        bitrix_id=11,
        title="gone",
        category_id=1,
        stage_id=stage.id,
        assigned_by_id=mgr.id,
        closed=False,
        missing_from_bitrix=False,
    )
    db_session.add_all([keep, gone])
    await db_session.commit()

    client = FakeBitrix(
        deals=[
            {
                "ID": "10",
                "TITLE": "keep",
                "CATEGORY_ID": "1",
                "STAGE_ID": "NEW",
                "CLOSED": "N",
                "OPPORTUNITY": "1",
            }
        ]
    )
    orch = SyncOrchestrator(db_session, client=client)  # type: ignore[arg-type]
    orch._sync_repo.try_advisory_lock = AsyncMock(return_value=True)  # type: ignore[method-assign]
    orch._sync_repo.advisory_unlock = AsyncMock()  # type: ignore[method-assign]

    await orch.run_deals(full=True)
    await db_session.refresh(keep)
    await db_session.refresh(gone)
    assert keep.missing_from_bitrix is False
    assert gone.missing_from_bitrix is True
    assert gone.missing_observed_at is not None


@pytest.mark.asyncio
async def test_activities_incremental_passes_last_updated(db_session: AsyncSession) -> None:
    repo = SyncRepository(db_session)
    await repo.set_state("last_activities_sync", {"at": "2024-01-01T12:00:00+00:00"})
    await db_session.commit()

    client = FakeBitrix(deals=[], activities=[])
    orch = SyncOrchestrator(db_session, client=client)  # type: ignore[arg-type]
    orch._sync_repo.try_advisory_lock = AsyncMock(return_value=True)  # type: ignore[method-assign]
    orch._sync_repo.advisory_unlock = AsyncMock()  # type: ignore[method-assign]

    await orch.run_activities(full=False)
    assert client.activity_calls
    assert ">=LAST_UPDATED" in client.activity_calls[0]
    assert ">=DATE_MODIFY" not in client.activity_calls[0]
    assert client.activity_calls[0]["OWNER_TYPE_ID"] == 2
    # Overlap applied (default SYNC_OVERLAP_MINUTES > 0) → before cursor instant
    assert client.activity_calls[0][">=LAST_UPDATED"] < "2024-01-01T12:00:00"


@pytest.mark.asyncio
async def test_activities_full_reconcile_skips_cursor_filter(db_session: AsyncSession) -> None:
    repo = SyncRepository(db_session)
    await repo.set_state("last_activities_sync", {"at": "2024-01-01T12:00:00+00:00"})
    await db_session.commit()

    client = FakeBitrix(deals=[], activities=[])
    orch = SyncOrchestrator(db_session, client=client)  # type: ignore[arg-type]
    orch._sync_repo.try_advisory_lock = AsyncMock(return_value=True)  # type: ignore[method-assign]
    orch._sync_repo.advisory_unlock = AsyncMock()  # type: ignore[method-assign]

    await orch.run_activities(full=True)
    assert client.activity_calls
    assert ">=LAST_UPDATED" not in client.activity_calls[0]
    assert client.activity_calls[0] == {"OWNER_TYPE_ID": 2}


@pytest.mark.asyncio
async def test_activities_rerun_window_idempotent_and_updates(db_session: AsyncSession) -> None:
    mgr = CrmManager(bitrix_id=1, name="A", last_name="B", is_active=True)
    pipe = CrmPipeline(bitrix_id=1, name="P", sort=0)
    db_session.add_all([mgr, pipe])
    await db_session.flush()
    stage = CrmStage(bitrix_id="NEW", pipeline_id=pipe.id, name="New", sort=0, semantics="process")
    deal = CrmDeal(
        bitrix_id=8581,
        title="control",
        category_id=1,
        stage_id=None,
        assigned_by_id=mgr.id,
        closed=False,
    )
    db_session.add_all([stage, deal])
    await db_session.commit()
    deal.stage_id = stage.id
    await db_session.commit()

    repo = SyncRepository(db_session)
    await repo.set_state("last_activities_sync", {"at": "2026-10-05T12:00:00+00:00"})
    await db_session.commit()

    client = FakeBitrix(deals=[], activities=list(LIVE_ACTIVITY_FIXTURE))
    orch = SyncOrchestrator(db_session, client=client)  # type: ignore[arg-type]
    orch._sync_repo.try_advisory_lock = AsyncMock(return_value=True)  # type: ignore[method-assign]
    orch._sync_repo.advisory_unlock = AsyncMock()  # type: ignore[method-assign]

    await orch.run_activities(full=False)
    count1 = (
        await db_session.execute(select(func.count()).select_from(CrmActivity))
    ).scalar_one()
    assert count1 == 2
    state1 = await repo.get_state("last_activities_sync")
    assert state1 and state1.get("at")
    cursor_after_ok = state1["at"]
    assert cursor_after_ok != "2026-10-05T12:00:00+00:00"

    # Second pass: same window payload → no duplicate rows; subject update applied
    updated = [dict(LIVE_ACTIVITY_FIXTURE[0]), dict(LIVE_ACTIVITY_FIXTURE[1])]
    updated[0]["SUBJECT"] = "Call updated"
    # Unchanged second activity keeps same fields
    client.activities = updated
    await orch.run_activities(full=False)

    count2 = (
        await db_session.execute(select(func.count()).select_from(CrmActivity))
    ).scalar_one()
    assert count2 == 2  # duplicates 0
    act = (
        await db_session.execute(select(CrmActivity).where(CrmActivity.bitrix_id == 900001))
    ).scalar_one()
    assert act.subject == "Call updated"
    unchanged = (
        await db_session.execute(select(CrmActivity).where(CrmActivity.bitrix_id == 900002))
    ).scalar_one()
    assert unchanged.subject == "Follow-up"

    await db_session.refresh(deal)
    assert deal.has_future_activity is True


@pytest.mark.asyncio
async def test_activities_failed_sync_does_not_advance_cursor(db_session: AsyncSession) -> None:
    repo = SyncRepository(db_session)
    await repo.set_state("last_activities_sync", {"at": "2026-01-01T00:00:00+00:00"})
    await db_session.commit()

    client = FakeBitrix(deals=[], activities=[])
    client.fail_activities = True
    orch = SyncOrchestrator(db_session, client=client)  # type: ignore[arg-type]
    orch._sync_repo.try_advisory_lock = AsyncMock(return_value=True)  # type: ignore[method-assign]
    orch._sync_repo.advisory_unlock = AsyncMock()  # type: ignore[method-assign]

    await orch.run_activities(full=False)
    state = await repo.get_state("last_activities_sync")
    assert state == {"at": "2026-01-01T00:00:00+00:00"}

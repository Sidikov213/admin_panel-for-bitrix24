"""Regression: failed sync must not advance last_deals_sync cursor."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.bitrix.client import BitrixClientError
from app.models.sync import SyncStatus
from app.repositories.sync import SyncRepository
from app.services.sync_service import SyncOrchestrator


class FailingBitrix:
    async def crm_deal_list(self, **filters):
        raise BitrixClientError("simulated outage")


class PartialFailBitrix:
    def __init__(self) -> None:
        self.calls = 0

    async def crm_deal_list(self, **filters):
        self.calls += 1
        return [
            {
                "ID": "1",
                "TITLE": "ok",
                "CATEGORY_ID": "1",
                "STAGE_ID": "NEW",
                "CLOSED": "N",
                "OPPORTUNITY": "10",
            },
            {
                "ID": "bad",  # will fail int()
                "TITLE": "bad",
                "CATEGORY_ID": "1",
                "CLOSED": "N",
            },
        ]


@pytest.mark.asyncio
async def test_bitrix_failure_does_not_advance_cursor(db_session: AsyncSession) -> None:
    repo = SyncRepository(db_session)
    await repo.set_state("last_deals_sync", {"at": "2020-01-01T00:00:00+00:00"})
    await db_session.commit()

    # Skip advisory lock on SQLite
    orch = SyncOrchestrator(db_session, client=FailingBitrix())  # type: ignore[arg-type]
    orch._sync_repo.try_advisory_lock = AsyncMock(return_value=True)  # type: ignore[method-assign]
    orch._sync_repo.advisory_unlock = AsyncMock()  # type: ignore[method-assign]

    await orch.run_deals(full=True)
    state = await repo.get_state("last_deals_sync")
    assert state is not None
    assert state["at"] == "2020-01-01T00:00:00+00:00"
    latest = await repo.latest_run()
    assert latest is not None
    assert latest.status == SyncStatus.failed


@pytest.mark.asyncio
async def test_upsert_errors_do_not_advance_cursor(db_session: AsyncSession) -> None:
    repo = SyncRepository(db_session)
    await repo.set_state("last_deals_sync", {"at": "2020-01-01T00:00:00+00:00"})
    await db_session.commit()

    orch = SyncOrchestrator(db_session, client=PartialFailBitrix())  # type: ignore[arg-type]
    orch._sync_repo.try_advisory_lock = AsyncMock(return_value=True)  # type: ignore[method-assign]
    orch._sync_repo.advisory_unlock = AsyncMock()  # type: ignore[method-assign]

    await orch.run_deals(full=True)
    state = await repo.get_state("last_deals_sync")
    assert state["at"] == "2020-01-01T00:00:00+00:00"
    latest = await repo.latest_run()
    assert latest is not None
    assert latest.status == SyncStatus.failed

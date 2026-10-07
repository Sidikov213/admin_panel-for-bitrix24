from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm import CrmDeal, CrmPipeline, CrmStage, DealChangeEvent, DealSnapshot
from app.services.deal_hash import compute_deal_content_hash
from app.services.sync_service import SyncOrchestrator


class FakeBitrix:
    pass


@pytest.mark.asyncio
async def test_snapshot_on_hash_change(db_session: AsyncSession) -> None:
    pipe = CrmPipeline(bitrix_id=1, name="P", sort=0)
    db_session.add(pipe)
    await db_session.flush()
    stage = CrmStage(bitrix_id="C1:NEW", pipeline_id=pipe.id, name="New", sort=0)
    db_session.add(stage)
    await db_session.flush()

    raw1 = {
        "ID": "100",
        "TITLE": "Deal A",
        "CATEGORY_ID": "1",
        "STAGE_ID": "C1:NEW",
        "CLOSED": "N",
        "OPPORTUNITY": "100",
    }
    orch = SyncOrchestrator(db_session, client=FakeBitrix())  # type: ignore[arg-type]
    await orch._upsert_deal(raw1)
    await db_session.commit()

    deal = (await db_session.execute(select(CrmDeal).where(CrmDeal.bitrix_id == 100))).scalar_one()
    snaps = (await db_session.execute(select(DealSnapshot).where(DealSnapshot.deal_id == deal.id))).scalars().all()
    assert len(snaps) == 1

    raw2 = {**raw1, "TITLE": "Deal B"}
    await orch._upsert_deal(raw2)
    await db_session.commit()
    events = (
        await db_session.execute(select(DealChangeEvent).where(DealChangeEvent.deal_id == deal.id))
    ).scalars().all()
    assert any(e.field_name == "title" for e in events)
    snaps2 = (await db_session.execute(select(DealSnapshot).where(DealSnapshot.deal_id == deal.id))).scalars().all()
    assert len(snaps2) == 2


@pytest.mark.asyncio
async def test_content_hash_stable() -> None:
    payload = {"ID": "1", "TITLE": "x"}
    assert compute_deal_content_hash(payload) == compute_deal_content_hash(payload)

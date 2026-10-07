"""Load clearly tagged demo CRM data when DEMO_MODE=true."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import utc_now
from app.models.crm import CrmDeal, CrmManager, CrmPipeline, CrmStage
from app.services.deal_hash import compute_deal_content_hash

DEMO_BITRIX_ID = 900001


async def seed_demo_data(session: AsyncSession) -> None:
    """Idempotent DEMO seed — safe to call on every API restart."""
    existing = await session.scalar(select(CrmDeal.id).where(CrmDeal.bitrix_id == DEMO_BITRIX_ID))
    if existing is not None:
        return

    mgr = await session.scalar(select(CrmManager).where(CrmManager.bitrix_id == DEMO_BITRIX_ID))
    if mgr is None:
        mgr = CrmManager(
            bitrix_id=DEMO_BITRIX_ID,
            name="Demo",
            last_name="Manager",
            is_active=True,
            raw={"demo": True},
        )
        session.add(mgr)

    pipe = await session.scalar(select(CrmPipeline).where(CrmPipeline.bitrix_id == DEMO_BITRIX_ID))
    if pipe is None:
        pipe = CrmPipeline(bitrix_id=DEMO_BITRIX_ID, name="[DEMO] Pipeline", sort=0)
        session.add(pipe)
    await session.flush()

    stage = await session.scalar(select(CrmStage).where(CrmStage.bitrix_id == "DEMO:NEW"))
    if stage is None:
        stage = CrmStage(
            bitrix_id="DEMO:NEW",
            pipeline_id=pipe.id,
            name="[DEMO] New",
            sort=0,
            semantics="process",
        )
        session.add(stage)
    await session.flush()

    now = utc_now()
    raw = {
        "ID": str(DEMO_BITRIX_ID),
        "TITLE": "[DEMO] Sample deal",
        "CATEGORY_ID": pipe.bitrix_id,
        "STAGE_ID": stage.bitrix_id,
    }
    deal = CrmDeal(
        bitrix_id=DEMO_BITRIX_ID,
        title="[DEMO] Sample deal",
        category_id=pipe.bitrix_id,
        stage_id=stage.id,
        assigned_by_id=mgr.id,
        opportunity=Decimal("100000"),
        currency_id="RUB",
        date_create=now,
        date_modify=now,
        closed=False,
        observed_at=now,
        content_hash=compute_deal_content_hash(raw),
        has_future_activity=False,
    )
    session.add(deal)
    await session.flush()

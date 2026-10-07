from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.kpi import compute_period_kpis
from app.core.timezone import utc_now
from app.models.crm import CrmDeal, CrmPipeline, CrmStage


@pytest.mark.asyncio
async def test_kpi_counts(db_session: AsyncSession) -> None:
    now = utc_now()
    pipe = CrmPipeline(bitrix_id=1, name="P", sort=0)
    db_session.add(pipe)
    await db_session.flush()
    stage_ok = CrmStage(bitrix_id="S1", pipeline_id=pipe.id, name="Won", sort=0, semantics="success")
    stage_proc = CrmStage(bitrix_id="S2", pipeline_id=pipe.id, name="Open", sort=1, semantics="process")
    db_session.add_all([stage_ok, stage_proc])
    await db_session.flush()

    db_session.add(
        CrmDeal(
            bitrix_id=1,
            title="Open deal",
            closed=False,
            stage_id=stage_proc.id,
            date_create=now,
            opportunity=Decimal("500"),
        )
    )
    db_session.add(
        CrmDeal(
            bitrix_id=2,
            title="Won deal",
            closed=True,
            stage_id=stage_ok.id,
            date_create=now,
            closedate=now,
            date_modify=now,
            opportunity=Decimal("1000"),
        )
    )
    await db_session.commit()

    today = date.today()
    start = today - timedelta(days=7)
    kpis = await compute_period_kpis(db_session, start, today)
    assert kpis["active_deals_count"] == 1
    assert kpis["won_count"] == 1
    assert kpis["new_deals_count"] >= 2

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.attention import money_requiring_attention, no_future_summary
from app.analytics.kpi import compute_period_kpis
from app.core.timezone import utc_now
from app.models.crm import CrmActivity, CrmDeal, CrmPipeline, CrmStage
from app.models.sync import SalesTarget
from app.models.targets import PeriodType
from app.services.targets_service import TargetsService


@pytest.mark.asyncio
async def test_money_requiring_attention_dedupes(db_session: AsyncSession) -> None:
    now = utc_now()
    pipe = CrmPipeline(bitrix_id=1, name="P", sort=0)
    db_session.add(pipe)
    await db_session.flush()
    stage = CrmStage(bitrix_id="S", pipeline_id=pipe.id, name="Open", sort=0, semantics="process")
    db_session.add(stage)
    await db_session.flush()

    # Deal A: no future
    db_session.add(
        CrmDeal(
            bitrix_id=101,
            title="No future",
            closed=False,
            stage_id=stage.id,
            category_id=1,
            opportunity=Decimal("1000"),
            has_future_activity=False,
        )
    )
    # Deal B: has future but overdue activity — also attention
    db_session.add(
        CrmDeal(
            bitrix_id=102,
            title="Overdue",
            closed=False,
            stage_id=stage.id,
            category_id=1,
            opportunity=Decimal("500"),
            has_future_activity=True,
        )
    )
    db_session.add(
        CrmActivity(
            bitrix_id=9001,
            owner_id=102,
            subject="Call",
            completed=False,
            deadline=now - timedelta(hours=3),
        )
    )
    # Deal C: both no_future AND overdue — count once
    db_session.add(
        CrmDeal(
            bitrix_id=103,
            title="Both",
            closed=False,
            stage_id=stage.id,
            category_id=1,
            opportunity=Decimal("200"),
            has_future_activity=False,
        )
    )
    db_session.add(
        CrmActivity(
            bitrix_id=9002,
            owner_id=103,
            subject="Task",
            completed=False,
            deadline=now - timedelta(hours=1),
        )
    )
    await db_session.commit()

    money = await money_requiring_attention(db_session)
    assert money["deals_count"] == 3
    assert money["amount"] == 1700.0

    nf = await no_future_summary(db_session)
    assert nf["deals_count"] == 2
    assert nf["amount"] == 1200.0


@pytest.mark.asyncio
async def test_plan_fact_won_metric(db_session: AsyncSession) -> None:
    now = utc_now()
    pipe = CrmPipeline(bitrix_id=39, name="X", sort=0)
    db_session.add(pipe)
    await db_session.flush()
    won = CrmStage(bitrix_id="W", pipeline_id=pipe.id, name="Won", sort=0, semantics="success")
    db_session.add(won)
    await db_session.flush()
    db_session.add(
        CrmDeal(
            bitrix_id=201,
            title="Won",
            closed=True,
            stage_id=won.id,
            opportunity=Decimal("3000"),
            closedate=now,
            date_modify=now,
        )
    )
    today = date.today()
    start = today.replace(day=1)
    db_session.add(
        SalesTarget(
            manager_id=None,
            period_type=PeriodType.month,
            period_start=start,
            period_end=today,
            amount=Decimal("10000"),
            currency="RUB",
        )
    )
    await db_session.commit()

    pf = await TargetsService(db_session).plan_fact_for_range(start, today)
    assert pf["plan_set"] is True
    assert pf["plan"] == 10000.0
    assert pf["fact"] == 3000.0
    assert pf["percent"] == 30.0
    assert pf["remaining"] == 7000.0
    assert pf["fact_metric"] == "sum_won_opportunity"

    empty = await TargetsService(db_session).plan_fact_for_range(
        today + timedelta(days=60), today + timedelta(days=90)
    )
    # No overlapping target for far future — but won deal also outside → plan may still overlap? use past empty
    # Use a range with no target rows
    db_session.add(
        SalesTarget(
            manager_id=None,
            period_type=PeriodType.week,
            period_start=date(2020, 1, 1),
            period_end=date(2020, 1, 7),
            amount=Decimal("1"),
        )
    )
    await db_session.commit()
    none_pf = await TargetsService(db_session).plan_fact_for_range(date(2021, 1, 1), date(2021, 1, 31))
    assert none_pf["plan_set"] is False
    assert none_pf["label"] == "План не задан"


@pytest.mark.asyncio
async def test_kpi_includes_attention_fields(db_session: AsyncSession) -> None:
    today = date.today()
    kpis = await compute_period_kpis(db_session, today - timedelta(days=7), today, include_series=False)
    assert "money_requiring_attention" in kpis
    assert "deals_requiring_attention_count" in kpis
    assert "deals_without_future_activity_amount" in kpis

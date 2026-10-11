"""Stage 2.5 — sales rules engine."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import resolve_preset
from app.core.timezone import utc_now
from app.models.crm import CrmActivity, CrmDeal, CrmManager, CrmPipeline, CrmStage
from app.models.sales_rules import SalesRule, SalesRuleViolation, ViolationStatus
from app.services.sales_rules.aggregates import dashboard_violation_kpis, manager_violation_stats
from app.services.sales_rules.engine import apply_detections, detect_all, evaluate_deal, preview_rule_impact
from app.services.sales_rules.humanize import describe_rule
from app.services.sales_rules.priority import pick_rules_by_check, rule_matches_deal


async def _seed_pipeline(db: AsyncSession) -> tuple[CrmPipeline, CrmStage, CrmManager]:
    pipe = CrmPipeline(bitrix_id=1, name="Сваи", sort=0)
    db.add(pipe)
    await db.flush()
    stage = CrmStage(bitrix_id="C1:NEW", pipeline_id=pipe.id, name="Квалификация", sort=0, semantics="process")
    db.add(stage)
    mgr = CrmManager(bitrix_id=77, name="Ivan", last_name="Test", is_active=True)
    db.add(mgr)
    await db.flush()
    return pipe, stage, mgr


@pytest.mark.asyncio
async def test_stage_rule_priority_over_pipeline(db_session: AsyncSession) -> None:
    pipe, stage, mgr = await _seed_pipeline(db_session)
    global_rule = SalesRule(
        rule_name="pipe",
        pipeline_bitrix_id=1,
        stage_id=None,
        enabled=True,
        max_idle_minutes=10000,
        severity="low",
    )
    stage_rule = SalesRule(
        rule_name="stage",
        pipeline_bitrix_id=1,
        stage_id=stage.id,
        enabled=True,
        max_idle_minutes=60,
        severity="high",
    )
    db_session.add_all([global_rule, stage_rule])
    await db_session.flush()

    matching = [global_rule, stage_rule]
    assert rule_matches_deal(stage_rule, category_id=1, stage_id=stage.id)
    chosen = pick_rules_by_check(matching)
    assert chosen["max_idle_minutes"].id == stage_rule.id
    assert chosen["max_idle_minutes"].severity == "high"


@pytest.mark.asyncio
async def test_disabled_rules_not_evaluated(db_session: AsyncSession) -> None:
    pipe, stage, mgr = await _seed_pipeline(db_session)
    db_session.add(
        SalesRule(
            rule_name="off",
            enabled=False,
            future_activity_required=True,
            severity="high",
        )
    )
    deal = CrmDeal(
        bitrix_id=501,
        title="D",
        closed=False,
        stage_id=stage.id,
        category_id=1,
        assigned_by_id=mgr.id,
        has_future_activity=False,
        opportunity=Decimal("100"),
    )
    db_session.add(deal)
    await db_session.flush()
    detected = await detect_all(db_session)
    assert detected == []


@pytest.mark.asyncio
async def test_no_future_and_overdue_and_idle(db_session: AsyncSession) -> None:
    pipe, stage, mgr = await _seed_pipeline(db_session)
    now = utc_now()
    rule = SalesRule(
        rule_name="combo",
        enabled=True,
        future_activity_required=True,
        overdue_activity_allowed=False,
        max_idle_minutes=30,
        severity="medium",
    )
    db_session.add(rule)
    deal = CrmDeal(
        bitrix_id=502,
        title="Idle",
        closed=False,
        stage_id=stage.id,
        category_id=1,
        assigned_by_id=mgr.id,
        has_future_activity=False,
        last_observed_activity_at=now - timedelta(hours=2),
        opportunity=Decimal("5000"),
    )
    db_session.add(deal)
    await db_session.flush()
    db_session.add(
        CrmActivity(
            bitrix_id=9001,
            owner_id=502,
            owner_type_id=2,
            completed=False,
            deadline=now - timedelta(hours=1),
            subject="call",
        )
    )
    await db_session.flush()

    detected = await detect_all(db_session, rules=[rule], now=now)
    types = {d.violation_type for d in detected}
    assert "NO_FUTURE_ACTIVITY" in types
    assert "OVERDUE_ACTIVITY" in types
    assert "IDLE_TOO_LONG" in types


@pytest.mark.asyncio
async def test_stage_duration(db_session: AsyncSession) -> None:
    pipe, stage, mgr = await _seed_pipeline(db_session)
    now = utc_now()
    rule = SalesRule(
        rule_name="stage dur",
        enabled=True,
        max_stage_duration_minutes=60,
        severity="high",
    )
    deal = CrmDeal(
        bitrix_id=503,
        title="Long stage",
        closed=False,
        stage_id=stage.id,
        category_id=1,
        assigned_by_id=mgr.id,
        has_future_activity=True,
        stage_changed_observed_at=now - timedelta(hours=5),
    )
    db_session.add_all([rule, deal])
    await db_session.flush()
    hits = evaluate_deal(deal, now=now, overdue_owners=set(), snapshot=None, rules=[rule])
    assert any(h.violation_type == "STAGE_TOO_LONG" for h in hits)


@pytest.mark.asyncio
async def test_required_fields_from_deal_columns(db_session: AsyncSession) -> None:
    pipe, stage, mgr = await _seed_pipeline(db_session)
    rule = SalesRule(
        rule_name="fields",
        enabled=True,
        required_fields=["TITLE", "OPPORTUNITY"],
        severity="medium",
    )
    deal = CrmDeal(
        bitrix_id=504,
        title="",
        closed=False,
        stage_id=stage.id,
        category_id=1,
        assigned_by_id=mgr.id,
        has_future_activity=True,
        opportunity=None,
    )
    db_session.add_all([rule, deal])
    await db_session.flush()
    hits = evaluate_deal(deal, now=utc_now(), overdue_owners=set(), snapshot={}, rules=[rule])
    assert any(h.violation_type == "REQUIRED_FIELD_MISSING" for h in hits)


@pytest.mark.asyncio
async def test_preview_does_not_persist(db_session: AsyncSession) -> None:
    pipe, stage, mgr = await _seed_pipeline(db_session)
    db_session.add(
        CrmDeal(
            bitrix_id=505,
            title="P",
            closed=False,
            stage_id=stage.id,
            category_id=1,
            assigned_by_id=mgr.id,
            has_future_activity=False,
            opportunity=Decimal("1000"),
        )
    )
    await db_session.flush()
    impact = await preview_rule_impact(
        db_session,
        {"future_activity_required": True, "severity": "high", "pipeline_bitrix_id": 1},
    )
    assert impact["deals_affected"] >= 1
    assert impact["persisted"] is False
    from sqlalchemy import func, select

    cnt = (await db_session.execute(select(func.count()).select_from(SalesRuleViolation))).scalar_one()
    assert int(cnt or 0) == 0


@pytest.mark.asyncio
async def test_duplicate_prevention_and_resolution_reopen(db_session: AsyncSession) -> None:
    pipe, stage, mgr = await _seed_pipeline(db_session)
    rule = SalesRule(rule_name="dup", enabled=True, future_activity_required=True, severity="high")
    deal = CrmDeal(
        bitrix_id=506,
        title="R",
        closed=False,
        stage_id=stage.id,
        category_id=1,
        assigned_by_id=mgr.id,
        has_future_activity=False,
    )
    db_session.add_all([rule, deal])
    await db_session.flush()

    d1 = await detect_all(db_session, rules=[rule])
    s1 = await apply_detections(db_session, d1)
    assert s1["created"] == 1
    d2 = await detect_all(db_session, rules=[rule])
    s2 = await apply_detections(db_session, d2)
    assert s2["created"] == 0
    assert s2["kept"] == 1

    # resolve by fixing
    deal.has_future_activity = True
    await db_session.flush()
    d3 = await detect_all(db_session, rules=[rule])
    s3 = await apply_detections(db_session, d3)
    assert s3["resolved"] == 1

    # reopen → new occurrence
    deal.has_future_activity = False
    await db_session.flush()
    d4 = await detect_all(db_session, rules=[rule])
    s4 = await apply_detections(db_session, d4)
    assert s4["created"] == 1

    from sqlalchemy import func, select

    total = (await db_session.execute(select(func.count()).select_from(SalesRuleViolation))).scalar_one()
    open_n = (
        await db_session.execute(
            select(func.count())
            .select_from(SalesRuleViolation)
            .where(SalesRuleViolation.status == ViolationStatus.open.value)
        )
    ).scalar_one()
    assert int(total) == 2
    assert int(open_n) == 1


@pytest.mark.asyncio
async def test_dashboard_and_manager_aggregates(db_session: AsyncSession) -> None:
    pipe, stage, mgr = await _seed_pipeline(db_session)
    rule = SalesRule(rule_name="agg", enabled=True, future_activity_required=True, severity="critical")
    deal = CrmDeal(
        bitrix_id=507,
        title="A",
        closed=False,
        stage_id=stage.id,
        category_id=1,
        assigned_by_id=mgr.id,
        has_future_activity=False,
        opportunity=Decimal("2000"),
    )
    db_session.add_all([rule, deal])
    await db_session.flush()
    await apply_detections(db_session, await detect_all(db_session, rules=[rule]))

    dash = await dashboard_violation_kpis(db_session)
    assert dash["deals_with_violations"] == 1
    assert dash["high_severity_violations"] >= 1
    assert dash["amount_under_violations"] == 2000.0

    mgr_stats = await manager_violation_stats(db_session)
    assert mgr.id in mgr_stats
    assert mgr_stats[mgr.id]["open_violations"] >= 1
    assert mgr_stats[mgr.id]["violation_rate"] is not None


def test_human_description_and_timezone_preset() -> None:
    text = describe_rule(
        {
            "future_activity_required": True,
            "severity": "high",
            "enabled": False,
            "stage_id": 1,
        },
        stage_name="Квалификация",
    )
    assert "Квалификация" in text
    assert "HIGH" in text
    rng = resolve_preset("current_week")
    assert rng.start <= rng.end


def test_comment_capability_documented_in_description() -> None:
    text = describe_rule({"required_comment": True, "severity": "medium"})
    assert "недоступна" in text.lower() or "disabled" in text.lower()

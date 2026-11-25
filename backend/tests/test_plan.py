"""Plan vs fact: progress math, fact attribution, target validation, digest line."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.plan import compute_progress, targets_progress
from app.auth.password import hash_password
from app.models.auth import User, UserRole
from app.models.crm import CrmDeal, CrmManager, CrmPipeline, CrmStage
from app.models.sync import SalesTarget
from app.models.targets import PeriodType
from app.notifications.digest import build_digest, render_manager_digest, render_team_digest

NOV_1, NOV_30 = date(2026, 11, 1), date(2026, 11, 30)


def _target(amount: str = "300000", manager_id: int | None = None) -> SalesTarget:
    return SalesTarget(
        id=1,
        manager_id=manager_id,
        period_type=PeriodType.month,
        period_start=NOV_1,
        period_end=NOV_30,
        amount=Decimal(amount),
        currency="RUB",
    )


def _progress(fact: str, on: date):
    return compute_progress(_target(), fact=Decimal(fact), won_count=1, on=on, manager_name=None)


def test_progress_math_mid_period() -> None:
    p = _progress("120000", date(2026, 11, 10))  # 10 of 30 days elapsed
    assert p.percent == 40.0
    assert p.expected == Decimal("100000")
    assert p.forecast == Decimal("360000")
    assert p.forecast_percent == 120.0
    assert p.remaining == Decimal("180000")
    assert (p.days_elapsed, p.days_left) == (10, 20)
    assert p.per_day_needed == Decimal("9000")
    assert p.status == "on_track" and p.active


@pytest.mark.parametrize(
    ("fact", "on", "status"),
    [
        ("90000", date(2026, 11, 10), "at_risk"),  # forecast 270k = 90% of plan
        ("50000", date(2026, 11, 10), "behind"),
        ("300000", date(2026, 11, 10), "done"),
        ("200000", date(2026, 12, 5), "missed"),
        ("0", date(2026, 10, 20), "not_started"),
        # Day 2 of 30: run-rate is noise, no on_track/behind verdict yet
        ("100000", date(2026, 11, 2), "early"),
        ("0", date(2026, 11, 5), "early"),
        ("300000", date(2026, 11, 2), "done"),
    ],
)
def test_progress_status(fact: str, on: date, status: str) -> None:
    assert _progress(fact, on).status == status


def test_forecast_reliability_window() -> None:
    early = _progress("100000", date(2026, 11, 2))
    assert early.forecast_reliable is False and early.forecast_in_days == 4  # reliable from day 6 of 30
    assert _progress("100000", date(2026, 11, 6)).forecast_reliable is True


def test_finished_period_forecast_is_fact() -> None:
    p = _progress("200000", date(2026, 12, 5))
    assert p.forecast == Decimal("200000") and p.days_left == 0 and not p.active


async def _seed(session: AsyncSession) -> dict:
    pipe = CrmPipeline(bitrix_id=1, name="P", sort=0)
    session.add(pipe)
    await session.flush()
    won = CrmStage(bitrix_id="C1:WON", pipeline_id=pipe.id, name="Won", sort=9, semantics="success")
    lost = CrmStage(bitrix_id="C1:LOSE", pipeline_id=pipe.id, name="Lost", sort=10, semantics="failure")
    ivan = CrmManager(bitrix_id=7, name="Иван", last_name="Петров")
    olga = CrmManager(bitrix_id=8, name="Ольга", last_name="Смирнова")
    session.add_all([won, lost, ivan, olga])
    await session.flush()

    def deal(bid: int, mgr: CrmManager, amount: str, closed_on: datetime, stage=won, **kw) -> CrmDeal:
        return CrmDeal(
            bitrix_id=bid, title=f"d{bid}", category_id=1, stage_id=stage.id, assigned_by_id=mgr.id,
            opportunity=Decimal(amount), closed=True, closedate=closed_on, **kw,
        )

    in_nov = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
    session.add_all(
        [
            deal(1, ivan, "100000", in_nov),
            deal(2, ivan, "50000", in_nov),
            deal(3, olga, "70000", in_nov),
            deal(4, ivan, "999999", datetime(2026, 10, 31, 12, tzinfo=timezone.utc)),  # previous month
            deal(5, ivan, "888888", in_nov, stage=lost),  # lost, not won
            deal(6, olga, "777777", in_nov, missing_from_bitrix=True),  # gone from Bitrix
            # 1 Nov 00:30 Moscow = 31 Oct 21:30 UTC → belongs to November
            deal(7, olga, "1000", datetime(2026, 10, 31, 21, 30, tzinfo=timezone.utc)),
        ]
    )
    session.add_all(
        [
            SalesTarget(manager_id=None, period_type=PeriodType.month, period_start=NOV_1, period_end=NOV_30,
                        amount=Decimal("600000"), currency="RUB"),
            SalesTarget(manager_id=ivan.id, period_type=PeriodType.month, period_start=NOV_1, period_end=NOV_30,
                        amount=Decimal("200000"), currency="RUB"),
        ]
    )
    await session.commit()
    return {"ivan": ivan, "olga": olga}


@pytest.mark.asyncio
async def test_fact_attribution(db_session: AsyncSession) -> None:
    seeded = await _seed(db_session)
    items = await targets_progress(db_session, date(2026, 11, 10))
    dept, ivan = items
    assert dept.manager_id is None
    assert dept.fact == Decimal("221000") and dept.won_count == 4
    assert ivan.manager_id == seeded["ivan"].id and ivan.manager_name == "Петров Иван"
    assert ivan.fact == Decimal("150000") and ivan.percent == 75.0

    only_ivan = await targets_progress(db_session, date(2026, 11, 10), manager_id=seeded["ivan"].id)
    assert [p.target_id for p in only_ivan] == [ivan.target_id]
    assert await targets_progress(db_session, date(2026, 12, 10)) == []
    assert len(await targets_progress(db_session, date(2026, 12, 10), active_only=False)) == 2


@pytest.mark.asyncio
async def test_digest_shows_plan(db_session: AsyncSession, monkeypatch) -> None:
    seeded = await _seed(db_session)
    digest = await build_digest(db_session, today=date(2026, 11, 10))
    team = render_team_digest(digest)
    assert "🎯 План 01.11–30.11: 221 000 ₽ из 600 000 ₽ — 36,8% · прогноз 110,5% (в графике)" in team
    ivan = next(m for m in digest.managers_all if m.manager_id == seeded["ivan"].id)
    assert "150 000 ₽ из 200 000 ₽ — 75%" in render_manager_digest(digest, ivan)

    early = render_team_digest(await build_digest(db_session, today=date(2026, 11, 2)))
    assert "прогноз через 4 дн." in early


async def _admin(client: AsyncClient, session: AsyncSession, role: UserRole = UserRole.admin) -> dict:
    email = f"{role.value}-plan@ex.com"
    session.add(User(email=email, password_hash=hash_password("password123"), role=role, is_active=True))
    await session.commit()
    await client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return {"X-CSRF-Token": client.cookies.get("focus_csrf") or ""}


BODY = {"period_type": "month", "period_start": "2026-11-01", "period_end": "2026-11-30", "amount": "500000"}


@pytest.mark.asyncio
async def test_target_validation_and_duplicates(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await _admin(client, db_session)
    ok = await client.post("/api/v1/targets", json=BODY, headers=headers)
    assert ok.status_code == 201

    dup = await client.post("/api/v1/targets", json=BODY, headers=headers)
    assert dup.status_code == 409  # department target: NULL manager_id bypasses the DB constraint

    cases = [
        {**BODY, "period_end": "2026-10-01"},
        {**BODY, "period_end": "2028-01-01"},
        {**BODY, "manager_id": 999},
        {**BODY, "currency": "rub"},
        {**BODY, "amount": "0"},
    ]
    for body in cases:
        r = await client.post("/api/v1/targets", json=body, headers=headers)
        assert r.status_code == 422, body

    target_id = ok.json()["id"]
    bad_patch = await client.patch(f"/api/v1/targets/{target_id}", json={"period_end": "2026-10-01"}, headers=headers)
    assert bad_patch.status_code == 422
    null_amount = await client.patch(f"/api/v1/targets/{target_id}", json={"amount": None}, headers=headers)
    assert null_amount.status_code == 422
    patched = await client.patch(f"/api/v1/targets/{target_id}", json={"amount": "550000"}, headers=headers)
    assert patched.status_code == 200 and Decimal(patched.json()["amount"]) == Decimal("550000")


@pytest.mark.asyncio
async def test_progress_endpoint(client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed(db_session)
    await _admin(client, db_session, UserRole.viewer)
    r = await client.get("/api/v1/targets/progress", params={"on": "2026-11-10"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["manager_id"] is None for i in items] == [True, False]
    assert items[0]["fact"] == 221000.0 and items[0]["status"] in {"on_track", "at_risk", "behind"}
    viewer_create = await client.post("/api/v1/targets", json=BODY, headers={"X-CSRF-Token": client.cookies.get("focus_csrf") or ""})
    assert viewer_create.status_code == 403


@pytest.mark.asyncio
async def test_plan_in_profit_reads_the_live_profit_field(client: AsyncClient, db_session: AsyncSession) -> None:
    from sqlalchemy import select

    from app.analytics.plan import target_series
    from app.repositories.sync import SyncRepository
    from app.services.sync_service import DEAL_FIELDS_STATE

    seeded = await _seed(db_session)
    # Two fields with one label: the first is abandoned, managers fill the second
    await SyncRepository(db_session).set_state(
        DEAL_FIELDS_STATE,
        {
            "UF_CRM_OLD": {"label": "Прибыль по расчету", "type": "string"},
            "UF_CRM_LIVE": {"label": "Прибыль по расчету", "type": "string"},
        },
    )
    profits = {1: "20 000", 2: "30500,50", 3: "неизвестно", 7: "1000", 5: "999999"}
    for d in (await db_session.execute(select(CrmDeal))).scalars():
        d.raw = {"UF_CRM_OLD": "", "UF_CRM_LIVE": profits.get(d.bitrix_id, "")}
    db_session.add(
        SalesTarget(manager_id=seeded["olga"].id, period_type=PeriodType.month, period_start=NOV_1,
                    period_end=NOV_30, amount=Decimal("10000"), currency="RUB", metric="profit")
    )
    for t in (await db_session.execute(select(SalesTarget).where(SalesTarget.manager_id.is_(None)))).scalars():
        t.metric, t.amount = "profit", Decimal("100000")
    await db_session.commit()

    items = await targets_progress(db_session, date(2026, 11, 10))
    dept = next(p for p in items if p.manager_id is None)
    ivan = next(p for p in items if p.manager_id == seeded["ivan"].id)
    olga = next(p for p in items if p.manager_id == seeded["olga"].id)
    # «неизвестно» is 0; the lost deal's profit is not counted
    assert dept.metric == "profit" and dept.fact == Decimal("51501")
    assert olga.fact == Decimal("1000") and olga.percent == 10.0
    # Ivan's plan stays in revenue
    assert ivan.metric == "revenue" and ivan.fact == Decimal("150000")
    assert "План по прибыли" in render_team_digest(await build_digest(db_session, today=date(2026, 11, 10)))

    target = (await db_session.execute(select(SalesTarget).where(SalesTarget.manager_id.is_(None)))).scalar_one()
    series = await target_series(db_session, target, date(2026, 11, 10))
    points = {p["date"]: p for p in series["points"]}
    assert len(series["points"]) == 30 and series["plan"] == 100000
    assert points["2026-11-01"]["fact"] == 1000  # 00:30 Moscow on the 1st
    assert points["2026-11-05"]["fact"] == points["2026-11-10"]["fact"] == 51501
    assert points["2026-11-11"]["fact"] is None and points["2026-11-30"]["pace"] == 100000


@pytest.mark.asyncio
async def test_scheduled_mounts_and_department_sum(client: AsyncClient, db_session: AsyncSession) -> None:
    from sqlalchemy import delete, select

    from app.repositories.sync import SyncRepository
    from app.services.sync_service import DEAL_FIELDS_STATE

    seeded = await _seed(db_session)
    ivan, olga = seeded["ivan"], seeded["olga"]
    await SyncRepository(db_session).set_state(
        DEAL_FIELDS_STATE,
        {
            "UF_PROFIT": {"label": "Прибыль по расчету", "type": "string"},
            "UF_MOUNT": {"label": "Дата монтажа", "type": "date"},
        },
    )
    pipe_id = (await db_session.execute(select(CrmStage.pipeline_id))).scalars().first()
    graph = CrmStage(bitrix_id="C1:EXECUTING", pipeline_id=pipe_id, name="Поставлен в график/монтаж", sort=7, semantics="process")
    pay = CrmStage(bitrix_id="C1:PAY", pipeline_id=pipe_id, name="Ждем итоговую оплату после монтажа (безнал)", sort=8, semantics="process")
    work = CrmStage(bitrix_id="C1:NEW", pipeline_id=pipe_id, name="В работе/КП", sort=5, semantics="process")
    db_session.add_all([graph, pay, work])
    await db_session.flush()
    # Won deals of the seed: 1 is mounted in November, 2 back in October, 3 has no mount date
    mounts = {1: "2026-11-04T03:00:00+03:00", 2: "2026-10-28T03:00:00+03:00", 5: "2026-11-06T03:00:00+03:00"}
    for d in (await db_session.execute(select(CrmDeal))).scalars():
        d.raw = {"UF_PROFIT": "10000", "UF_MOUNT": mounts.get(d.bitrix_id, "")}

    def open_deal(bid: int, mgr: CrmManager, stage: CrmStage, mount: str, profit: str = "5000", **kw) -> CrmDeal:
        return CrmDeal(
            bitrix_id=bid, title=f"d{bid}", category_id=1, stage_id=stage.id, assigned_by_id=mgr.id,
            opportunity=Decimal("90000"), closed=False, raw={"UF_PROFIT": profit, "UF_MOUNT": mount}, **kw,
        )

    db_session.add_all(
        [
            open_deal(20, ivan, graph, "2026-11-30T03:00:00+03:00"),  # last day of the period
            open_deal(21, olga, pay, "2026-11-12T03:00:00+03:00", profit="7 000"),
            open_deal(22, ivan, graph, "2026-12-01T03:00:00+03:00"),  # next month
            open_deal(23, ivan, work, "2026-11-15T03:00:00+03:00"),  # not scheduled yet
            open_deal(24, olga, graph, "2026-11-20T03:00:00+03:00", is_excluded=True),
        ]
    )
    await db_session.execute(delete(SalesTarget))
    db_session.add_all(
        [
            SalesTarget(manager_id=m.id, period_type=PeriodType.month, period_start=NOV_1, period_end=NOV_30,
                        amount=Decimal(amount), currency="RUB", metric="profit")
            for m, amount in ((ivan, "40000"), (olga, "20000"))
        ]
    )
    await db_session.commit()

    items = await targets_progress(db_session, date(2026, 11, 10))
    dept = next(p for p in items if p.manager_id is None)
    p_ivan = next(p for p in items if p.manager_id == ivan.id)
    p_olga = next(p for p in items if p.manager_id == olga.id)
    # Ivan: won deal 1 (10 000) + scheduled deal 20 (5 000); the lost deal 5 is not counted
    assert (p_ivan.scheduled, p_ivan.scheduled_count, p_ivan.scheduled_percent) == (Decimal("15000"), 2, 37.5)
    assert (p_olga.scheduled, p_olga.scheduled_count) == (Decimal("7000"), 1)
    # No department target: the managers' plans and numbers added up
    assert dept.virtual and dept.target_id < 0 and items[0] is dept
    assert (dept.plan, dept.fact, dept.scheduled) == (Decimal("60000"), Decimal("40000"), Decimal("22000"))
    assert not p_ivan.virtual

    await _admin(client, db_session, UserRole.viewer)
    r = await client.get(
        "/api/v1/targets/department/series",
        params={"period_start": "2026-11-01", "period_end": "2026-11-30", "metric": "profit"},
    )
    assert r.status_code == 200 and r.json()["plan"] == 60000 and len(r.json()["points"]) == 30
    missing = await client.get(
        "/api/v1/targets/department/series",
        params={"period_start": "2026-12-01", "period_end": "2026-12-31", "metric": "profit"},
    )
    assert missing.status_code == 404

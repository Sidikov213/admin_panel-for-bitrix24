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

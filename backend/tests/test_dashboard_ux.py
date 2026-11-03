"""Dashboard filters, period comparison, KPI → deal list drill-down parity, CSV export."""

import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password
from app.models.auth import User, UserRole
from app.models.crm import CrmActivity, CrmDeal, CrmManager, CrmPipeline, CrmStage, DealChangeEvent
from app.services.dashboard_service import previous_period

TODAY = date(2026, 11, 20)
PERIOD = {"period_start": "2026-11-01", "period_end": "2026-11-30"}


def at(month: int, day: int) -> datetime:
    return datetime(2026, month, day, 12, tzinfo=timezone.utc)


def test_previous_period_same_length() -> None:
    assert previous_period(date(2026, 11, 1), date(2026, 11, 30)) == (date(2026, 10, 2), date(2026, 10, 31))
    assert previous_period(date(2026, 11, 10), date(2026, 11, 16)) == (date(2026, 11, 3), date(2026, 11, 9))


async def _seed(session: AsyncSession) -> dict:
    pipes = [CrmPipeline(bitrix_id=1, name="Сваи", sort=0), CrmPipeline(bitrix_id=39, name="Отложенный", sort=1)]
    session.add_all(pipes)
    await session.flush()
    new = CrmStage(bitrix_id="C1:NEW", pipeline_id=pipes[0].id, name="Новая", sort=10, semantics="process")
    kp = CrmStage(bitrix_id="C1:KP", pipeline_id=pipes[0].id, name="КП", sort=20, semantics="process")
    won = CrmStage(bitrix_id="C1:WON", pipeline_id=pipes[0].id, name="Успешно", sort=90, semantics="success")
    lost = CrmStage(bitrix_id="C1:LOSE", pipeline_id=pipes[0].id, name="Провал", sort=99, semantics="failure")
    ivan = CrmManager(bitrix_id=7, name="Иван", last_name="Петров")
    olga = CrmManager(bitrix_id=8, name="Ольга", last_name="Смирнова")
    session.add_all([new, kp, won, lost, ivan, olga])
    await session.flush()
    now = datetime.now(timezone.utc)

    def deal(bid, mgr, stage, created, *, cat=1, closed=False, closedate=None, future=True, amount="100000", title=None):
        return CrmDeal(
            bitrix_id=bid, title=title or f"Сделка {bid}", category_id=cat, stage_id=stage.id, assigned_by_id=mgr.id,
            opportunity=Decimal(amount), date_create=created, date_modify=closedate or created, closed=closed,
            closedate=closedate, has_future_activity=future,
        )

    deals = [
        deal(1, ivan, new, at(11, 3), future=False, title="=HYPERLINK(\"x\")"),  # new, open, no future
        deal(2, ivan, won, at(11, 4), closed=True, closedate=at(11, 15), amount="300000"),
        deal(3, olga, lost, at(11, 5), closed=True, closedate=at(11, 16)),
        deal(4, olga, kp, at(10, 10)),  # created last period, still open
        deal(5, olga, won, at(10, 1), closed=True, closedate=at(10, 20), amount="50000"),  # won last period
        deal(6, ivan, new, at(11, 6), cat=39, future=False),  # other pipeline
    ]
    session.add_all(deals)
    await session.flush()
    session.add_all(
        [
            CrmActivity(bitrix_id=1, owner_type_id=2, owner_id=4, deadline=now - timedelta(days=1), completed=False),
            CrmActivity(bitrix_id=2, owner_type_id=2, owner_id=6, deadline=now - timedelta(days=1), completed=False),
            DealChangeEvent(deal_id=deals[3].id, field_name="stage_id", old_value=str(new.id), new_value=str(kp.id),
                            observed_at=now),
            DealChangeEvent(deal_id=deals[0].id, field_name="assigned_by_id", old_value=str(olga.id),
                            new_value=str(ivan.id), observed_at=now - timedelta(hours=1)),
        ]
    )
    session.add(User(email="v@ex.com", password_hash=hash_password("password123"), role=UserRole.viewer, is_active=True))
    await session.commit()
    return {"ivan": ivan, "olga": olga}


async def _login(client: AsyncClient) -> None:
    r = await client.post("/api/v1/auth/login", json={"email": "v@ex.com", "password": "password123"})
    assert r.status_code == 200


async def _total(client: AsyncClient, **params) -> int:
    r = await client.get("/api/v1/deals", params={k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()})
    assert r.status_code == 200, r.text
    return r.json()["total"]


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [{}, {"pipeline": 1}, {"manager": "ivan"}])
async def test_kpi_drilldown_lists_exactly_the_counted_deals(client: AsyncClient, db_session: AsyncSession, scope) -> None:
    seeded = await _seed(db_session)
    await _login(client)
    dash_params, deal_params = dict(PERIOD), {}
    if "pipeline" in scope:
        dash_params["pipeline_id"] = deal_params["category_id"] = scope["pipeline"]
    if "manager" in scope:
        dash_params["manager_id"] = deal_params["manager_id"] = seeded[scope["manager"]].id

    k = (await client.get("/api/v1/dashboard", params=dash_params)).json()["kpis"]
    created = {"created_from": PERIOD["period_start"], "created_to": PERIOD["period_end"]}
    closed = {"closed_from": PERIOD["period_start"], "closed_to": PERIOD["period_end"]}
    assert k["new_deals_count"] == await _total(client, **deal_params, **created)
    assert k["won_count"] == await _total(client, **deal_params, **closed, outcome="won")
    assert k["lost_count"] == await _total(client, **deal_params, **closed, outcome="lost")
    assert k["active_deals_count"] == await _total(client, **deal_params, closed=False)
    assert k["deals_without_future_activity_count"] == await _total(
        client, **deal_params, closed=False, has_future_activity=False
    )
    # Overdue KPI counts activities; the drill-down lists deals that have them (one each here)
    assert k["open_overdue"] == await _total(client, **deal_params, overdue=True)


@pytest.mark.asyncio
async def test_comparison_with_previous_period(client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed(db_session)
    await _login(client)
    body = (await client.get("/api/v1/dashboard", params={**PERIOD, "pipeline_id": 1})).json()
    cmp = body["comparison"]
    assert (cmp["period_start"], cmp["period_end"]) == ("2026-10-02", "2026-10-31")
    m = cmp["metrics"]
    assert m["new_deals_count"] == {"previous": 1.0, "delta": 2.0, "delta_pct": 200.0}  # 3 vs deal 4
    assert m["sum_won_opportunity"]["delta_pct"] == 500.0  # 300k vs 50k
    assert m["lost_count"]["delta_pct"] is None  # nothing lost before: no percentage from zero


@pytest.mark.asyncio
async def test_recent_changes_scoped_and_readable(client: AsyncClient, db_session: AsyncSession) -> None:
    seeded = await _seed(db_session)
    await _login(client)
    all_changes = (await client.get("/api/v1/dashboard", params=PERIOD)).json()["recent_changes"]
    stage = next(c for c in all_changes if c["field_name"] == "stage_id")
    assert (stage["field_label"], stage["old_label"], stage["new_label"]) == ("Этап", "Новая", "КП")
    assert stage["deal_title"] == "Сделка 4"
    owner = next(c for c in all_changes if c["field_name"] == "assigned_by_id")
    assert (owner["old_label"], owner["new_label"]) == ("Смирнова Ольга", "Петров Иван")

    ivan_only = (
        await client.get("/api/v1/dashboard", params={**PERIOD, "manager_id": seeded["ivan"].id})
    ).json()["recent_changes"]
    assert [c["deal_title"] for c in ivan_only] == ['=HYPERLINK("x")']


@pytest.mark.asyncio
async def test_problem_deals_biggest_first_and_scoped(client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed(db_session)
    await _login(client)
    problems = (await client.get("/api/v1/dashboard", params={**PERIOD, "pipeline_id": 39})).json()["problem_deals"]
    assert [p["bitrix_id"] for p in problems] == [6]


@pytest.mark.asyncio
async def test_csv_export(client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed(db_session)
    await _login(client)
    r = await client.get("/api/v1/deals/export.csv", params={"category_id": 1, "sort_by": "opportunity", "sort_dir": "desc"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["x-total-count"] == "5" and r.headers["x-truncated"] == "false"
    text = r.content.decode("utf-8")
    assert text.startswith("﻿")
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";"))
    assert rows[0][:3] == ["ID в Bitrix", "Название", "Этап"]
    assert rows[1][1] == "Сделка 2" and rows[1][4] == "300000,00"  # biggest first, decimal comma
    titles = [row[1] for row in rows[1:]]
    assert "'=HYPERLINK(\"x\")" in titles  # formula neutralised
    assert (await client.get("/api/v1/deals/export.csv", params={"outcome": "nope"})).status_code == 422


@pytest.mark.asyncio
async def test_attention_block_and_pipeline_sums(client: AsyncClient, db_session: AsyncSession) -> None:
    seeded = await _seed(db_session)
    await _login(client)
    body = (await client.get("/api/v1/dashboard", params=PERIOD)).json()
    a = body["attention"]
    k = body["kpis"]
    # Same numbers as the KPI and the deal list behind it
    assert a["no_next_activity"] == k["deals_without_future_activity_count"] == 2
    assert a["overdue_deals"] == await _total(client, closed=False, overdue=True)
    assert a["stuck"] >= 0 and len(a["stuck_top"]) <= 3
    assert a["avito"] is None and a["ai"] is None  # no dialogs, no AI conclusions yet
    pipes = {p["name"]: p for p in body["charts"]["deals_by_pipeline"]}
    assert (pipes["Сваи"]["count"], pipes["Сваи"]["sum"]) == (2, 200000.0)
    assert pipes["Отложенный"]["sum"] == 100000.0

    # The AI line and Avito are department-wide: hidden under a manager filter
    scoped = (await client.get("/api/v1/dashboard", params={**PERIOD, "manager_id": seeded["ivan"].id})).json()
    assert scoped["attention"]["no_next_activity"] == 2 and scoped["attention"]["ai"] is None

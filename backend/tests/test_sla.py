"""Working calendar, stage deadlines, reaction speed, overdue report, activity completion time."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.overdue import overdue_report
from app.analytics.sla import default_rule, reaction_stats, stuck_deals
from app.auth.password import hash_password
from app.core.work_calendar import WorkCalendar, parse_holidays, parse_weekdays
from app.models.auth import User, UserRole
from app.models.crm import CrmActivity, CrmDeal, CrmManager, CrmPipeline, CrmStage, DealStageHistory, StageSlaRule
from app.services.sync_service import SyncOrchestrator

MSK = ZoneInfo("Europe/Moscow")
CAL = WorkCalendar(
    tz=MSK, workdays=parse_weekdays("mon-fri"), start=time(9), end=time(17), holidays=parse_holidays("12-26..01-11")
)


def msk(y: int, mo: int, d: int, h: int, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=MSK).astimezone(timezone.utc)


# --- calendar ------------------------------------------------------------------------


def test_friday_evening_lead_is_not_64_hours_late() -> None:
    # Fri 16:50 → Mon 09:20: 10 min on Friday + 20 min on Monday
    assert CAL.work_seconds(msk(2026, 11, 6, 16, 50), msk(2026, 11, 9, 9, 20)) == 30 * 60
    assert CAL.add_work_seconds(msk(2026, 11, 6, 16, 50), 3600) == msk(2026, 11, 9, 9, 50)


def test_company_vacation_and_weekday_parsing() -> None:
    # Fri 25.12 16:00 → Tue 12.01 10:00: 1 h before the vacation + 1 h after it
    assert CAL.work_seconds(msk(2026, 12, 25, 16), msk(2027, 1, 12, 10)) == 2 * 3600
    assert CAL.is_holiday(date(2027, 1, 1)) and not CAL.is_holiday(date(2027, 1, 12))
    assert parse_weekdays("mon-fri") == frozenset(range(5))
    assert parse_weekdays("fri-mon") == frozenset({4, 5, 6, 0})
    assert CAL.work_seconds(msk(2026, 11, 7, 10), msk(2026, 11, 8, 18)) == 0  # weekend


def test_default_rules_by_stage_name() -> None:
    assert default_rule("Не обработан")[:3] == (1, "work_hours", True)
    assert default_rule("Взят в работу (до первого контакта)")[:3] == (1, "work_hours", True)
    assert default_rule("Недозвон")[:2] == (7, "calendar_days")
    assert default_rule("Контакт установлен / Квалификация")[:2] == (10, "calendar_days")
    assert default_rule("В работе / КП с расчетом")[:2] == (10, "calendar_days")
    assert default_rule("Пробное бурение / Подготовка к монтажу")[0] is None  # not "монтаж" 30 days
    assert default_rule("Поставлен в график / Монтаж")[:2] == (30, "calendar_days")
    assert default_rule("Ждем итоговую оплату после монтажа (безнал)")[:2] == (7, "calendar_days")
    assert default_rule("Ближайшее время")[3] is False


# --- fixtures ------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _calendar(monkeypatch):
    monkeypatch.setattr("app.analytics.sla.get_work_calendar", lambda: CAL)


async def _pipeline(session: AsyncSession) -> dict:
    pipe = CrmPipeline(bitrix_id=1, name="Сваи", sort=0)
    session.add(pipe)
    await session.flush()
    st = {
        code: CrmStage(bitrix_id=f"C1:{code}", pipeline_id=pipe.id, name=name, sort=sort, semantics=sem)
        for code, name, sort, sem in [
            ("NEW", "Не обработан", 10, "process"),
            ("TAKEN", "Взят в работу (до первого контакта)", 20, "process"),
            ("NODIAL", "Недозвон", 30, "process"),
            ("QUAL", "Контакт установлен / Квалификация", 40, "process"),
            ("WON", "Сделка успешна", 90, "success"),
        ]
    }
    mgr = CrmManager(bitrix_id=7, name="Мария", last_name="Иванова")
    session.add_all([*st.values(), mgr])
    await session.flush()
    return {"st": st, "mgr": mgr}


def _deal(ctx, bid: int, stage: str, created: datetime, **kw) -> CrmDeal:
    return CrmDeal(
        bitrix_id=bid, title=f"Сделка {bid}", category_id=1, stage_id=ctx["st"][stage].id,
        assigned_by_id=ctx["mgr"].id, date_create=created, opportunity=Decimal("100000"), **kw,
    )


def _hist(hid: int, bid: int, stage: str, ts: datetime) -> DealStageHistory:
    return DealStageHistory(bitrix_id=hid, deal_bitrix_id=bid, stage_bitrix_id=f"C1:{stage}", category_id=1, created_time=ts)


NOW = msk(2026, 11, 9, 9, 20)  # Monday morning


# --- stuck deals ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stuck_deals_use_working_hours_and_stage_rules(db_session: AsyncSession) -> None:
    ctx = await _pipeline(db_session)
    db_session.add_all(
        [
            _deal(ctx, 1, "NEW", msk(2026, 11, 6, 16, 50)),  # 30 working minutes — fine
            _deal(ctx, 2, "NEW", msk(2026, 11, 6, 14)),  # 3 h 20 min — stuck
            _deal(ctx, 3, "NODIAL", msk(2026, 10, 30, 10)),  # 8+ days on «Недозвон» — stuck
            _deal(ctx, 4, "QUAL", msk(2026, 11, 1, 10), stage_changed_observed_at=msk(2026, 11, 6, 10)),
            _deal(ctx, 5, "NEW", msk(2026, 11, 1, 10), closed=True),
            _hist(1, 1, "NEW", msk(2026, 11, 6, 16, 50)),
            _hist(2, 2, "NEW", msk(2026, 11, 6, 14)),
            _hist(3, 3, "NEW", msk(2026, 10, 30, 10)),
            _hist(4, 3, "NODIAL", msk(2026, 10, 31, 10)),
            CrmActivity(bitrix_id=50, type_id=2, owner_type_id=2, owner_id=3, subject="Звонок клиенту",
                        created=msk(2026, 11, 8, 12), completed=True, completed_at=msk(2026, 11, 8, 12, 5)),
        ]
    )
    await db_session.commit()

    r = await stuck_deals(db_session, now=NOW)
    assert [i["bitrix_id"] for i in r["items"]] == [2, 3] or [i["bitrix_id"] for i in r["items"]] == [3, 2]
    by_id = {i["bitrix_id"]: i for i in r["items"]}
    assert by_id[2]["in_stage_seconds"] == 3 * 3600 + 20 * 60 and by_id[2]["rule"] == "1 раб. ч"
    assert by_id[3]["last_activity"]["type"] == "Звонок" and by_id[3]["in_stage_since_source"] == "bitrix"
    assert r["open_total"] == 4 and r["stuck_total"] == 2
    new_stage = next(s for s in r["by_stage"] if s["stage_id"] == "C1:NEW")
    assert (new_stage["open"], new_stage["stuck"]) == (2, 1)
    assert r["by_manager"][0]["share"] == 50.0

    every = await stuck_deals(db_session, now=NOW, only_stuck=False)
    assert {i["bitrix_id"] for i in every["items"]} == {1, 2, 3, 4}
    assert next(i for i in every["items"] if i["bitrix_id"] == 4)["in_stage_since_source"] == "observed"

    # Admin tightens «Квалификация» to 2 calendar days → deal 4 (3 days there) is now stuck
    db_session.add(StageSlaRule(stage_bitrix_id="C1:QUAL", threshold=Decimal(2), unit="calendar_days"))
    await db_session.commit()
    tightened = await stuck_deals(db_session, now=NOW)
    assert 4 in {i["bitrix_id"] for i in tightened["items"]}


# --- reaction ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reaction_speed_in_working_time(db_session: AsyncSession) -> None:
    ctx = await _pipeline(db_session)
    now = msk(2026, 11, 9, 12)
    db_session.add_all(
        [
            # Fast: taken in 20 min, first contact in 50 min
            _deal(ctx, 1, "QUAL", msk(2026, 11, 9, 10)),
            _hist(1, 1, "NEW", msk(2026, 11, 9, 10)),
            _hist(2, 1, "TAKEN", msk(2026, 11, 9, 10, 20)),
            _hist(3, 1, "QUAL", msk(2026, 11, 9, 10, 50)),
            # Friday 16:30 lead: taken Mon 09:30 (1 working hour), contact Mon 11:00 (2.5 h) → late
            _deal(ctx, 2, "NODIAL", msk(2026, 11, 6, 16, 30)),
            _hist(4, 2, "NEW", msk(2026, 11, 6, 16, 30)),
            _hist(5, 2, "TAKEN", msk(2026, 11, 9, 9, 30)),
            _hist(6, 2, "NODIAL", msk(2026, 11, 9, 11)),
            # Created before opening hours, still untouched at noon: waiting 3 working hours
            _deal(ctx, 3, "NEW", msk(2026, 11, 9, 8)),
            _hist(7, 3, "NEW", msk(2026, 11, 9, 8)),
        ]
    )
    await db_session.commit()

    r = await reaction_stats(db_session, period_start=date(2026, 11, 6), period_end=date(2026, 11, 9), now=now)
    rows = {w["bitrix_id"]: w for w in r["worst"]}
    assert (rows[1]["take_seconds"], rows[1]["contact_seconds"], rows[1]["late"]) == (1200, 3000, False)
    assert (rows[2]["take_seconds"], rows[2]["contact_seconds"], rows[2]["late"]) == (3600, 9000, True)
    assert rows[3]["waiting_seconds"] == 3 * 3600 and rows[3]["late"] is True
    s = r["summary"]
    assert (s["deals"], s["late"], s["waiting"], s["waiting_late"]) == (3, 2, 1, 1)
    assert s["contact"]["median_seconds"] == 6000
    assert r["norms"][1]["contact"] == 7200
    assert r["managers"][0]["name"] == "Иванова Мария"


# --- overdue report ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overdue_report_open_and_closed_late(db_session: AsyncSession) -> None:
    ctx = await _pipeline(db_session)
    db_session.add(_deal(ctx, 1, "QUAL", msk(2026, 11, 1, 10)))
    deadline = msk(2026, 11, 8, 10)

    def act(bid, *, completed=False, done=None, dl=deadline, owner_type=2):
        return CrmActivity(bitrix_id=bid, type_id=2, owner_type_id=owner_type, owner_id=1, subject=f"a{bid}",
                           deadline=dl, completed=completed, completed_at=done)

    db_session.add_all(
        [
            act(1),  # still open
            act(2, completed=True, done=deadline + timedelta(hours=5)),  # closed 5 h late
            act(3, completed=True, done=deadline - timedelta(hours=1)),  # closed in time
            act(4, completed=True, done=None),  # closed, moment unknown
            act(5, dl=msk(2026, 10, 1, 10)),  # deadline outside the period
            act(6, owner_type=1),  # a lead's activity
        ]
    )
    await db_session.commit()

    now = msk(2026, 11, 9, 10)
    r = await overdue_report(db_session, date_from=date(2026, 11, 2), date_to=date(2026, 11, 9), now=now)
    assert [i["bitrix_id"] for i in r["items"]] == [1, 2]
    assert r["items"][0]["overdue_seconds"] == 24 * 3600 and r["items"][0]["pipeline"] == "Сваи"
    s = r["summary"]
    assert (s["total"], s["open"], s["closed_late"], s["unknown_completion"]) == (2, 1, 1, 1)
    assert s["close_delay_median_seconds"] == 5 * 3600
    only_open = await overdue_report(db_session, date_from=date(2026, 11, 2), date_to=date(2026, 11, 9), now=now, only_open=True)
    assert [i["bitrix_id"] for i in only_open["items"]] == [1] and only_open["summary"]["total"] == 2


# --- activity completion time --------------------------------------------------------


@pytest.mark.asyncio
async def test_activity_completed_at_comes_from_first_completed_update(db_session: AsyncSession) -> None:
    orch = SyncOrchestrator(db_session, client=AsyncMock())  # type: ignore[arg-type]
    base = {"ID": "77", "OWNER_TYPE_ID": "2", "OWNER_ID": "1", "DEADLINE": "2026-11-08T10:00:00+03:00",
            "END_TIME": "2026-11-08T10:30:00+03:00"}
    a = await orch._upsert_activity({**base, "COMPLETED": "N", "LAST_UPDATED": "2026-11-07T09:00:00+03:00"})
    assert a.completed_at is None
    a = await orch._upsert_activity({**base, "COMPLETED": "Y", "LAST_UPDATED": "2026-11-08T15:00:00+03:00"})
    assert a.completed_at.astimezone(MSK).hour == 15  # not END_TIME (planned 10:30)
    a = await orch._upsert_activity({**base, "COMPLETED": "Y", "LAST_UPDATED": "2026-11-09T12:00:00+03:00"})
    assert a.completed_at.astimezone(MSK).day == 8  # a later edit keeps the completion moment
    a = await orch._upsert_activity({**base, "COMPLETED": "N", "LAST_UPDATED": "2026-11-09T13:00:00+03:00"})
    assert a.completed_at is None


# --- API -----------------------------------------------------------------------------


async def _login(client: AsyncClient, session: AsyncSession, role: UserRole) -> dict:
    email = f"{role.value}-sla@ex.com"
    session.add(User(email=email, password_hash=hash_password("password123"), role=role, is_active=True))
    await session.commit()
    await client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return {"X-CSRF-Token": client.cookies.get("focus_csrf") or ""}


@pytest.mark.asyncio
async def test_rules_api_permissions_override_and_reset(client: AsyncClient, db_session: AsyncSession) -> None:
    await _pipeline(db_session)
    headers = await _login(client, db_session, UserRole.viewer)
    rules = (await client.get("/api/v1/sla/rules")).json()["items"]
    qual = next(r for r in rules if r["stage_bitrix_id"] == "C1:QUAL")
    assert (qual["threshold"], qual["unit"], qual["source"]) == (10, "calendar_days", "default")
    body = {"threshold": 7, "unit": "calendar_days", "reaction_stage": False}
    assert (await client.put("/api/v1/sla/rules/C1:QUAL", json=body, headers=headers)).status_code == 403

    client.cookies.clear()
    headers = await _login(client, db_session, UserRole.admin)
    assert (await client.put("/api/v1/sla/rules/C1:QUAL", json=body)).status_code == 403  # no CSRF
    bad = await client.put("/api/v1/sla/rules/C1:QUAL", json={**body, "unit": "weeks"}, headers=headers)
    assert bad.status_code == 422
    ok = await client.put("/api/v1/sla/rules/C1:QUAL", json=body, headers=headers)
    assert ok.status_code == 200 and ok.json()["source"] == "custom" and ok.json()["label"] == "7 дн."
    untracked = await client.put("/api/v1/sla/rules/C1:QUAL", json={**body, "threshold": None}, headers=headers)
    assert untracked.json()["tracked"] is False
    reset = await client.delete("/api/v1/sla/rules/C1:QUAL", headers=headers)
    assert reset.json()["source"] == "default" and reset.json()["threshold"] == 10
    assert (await client.put("/api/v1/sla/rules/C9:NOPE", json=body, headers=headers)).status_code == 404

    for url in ("/api/v1/sla/stuck", "/api/v1/sla/reaction", "/api/v1/overdue?period=week", "/api/v1/overdue?period=today&only_open=true"):
        assert (await client.get(url)).status_code == 200, url
    assert (await client.get("/api/v1/overdue?period=decade")).status_code == 422

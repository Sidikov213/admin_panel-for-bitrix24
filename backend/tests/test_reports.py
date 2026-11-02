"""Daily / weekly / monthly reports: periods, content, archive, scheduled sending, API."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password
from app.core.config import get_settings
from app.core.work_calendar import get_work_calendar
from app.models.analytics import SalesReport
from app.models.auth import User, UserRole
from app.models.crm import CrmActivity, CrmDeal, CrmManager, CrmPipeline, CrmStage, DealStageHistory
from app.notifications.telegram import TelegramError
from app.reports.builder import build_report, period_for, previous_period, render_report, report_period_for_schedule
from app.reports.service import generate_report, run_scheduled_report

MSK = ZoneInfo("Europe/Moscow")
DAY = date(2026, 10, 6)  # Tuesday


def msk(mo: int, d: int, h: int = 12) -> datetime:
    return datetime(2026, mo, d, h, tzinfo=MSK).astimezone(timezone.utc)


class RecordingTelegram:
    def __init__(self, fail: set[str] | None = None) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = fail or set()

    async def send_message(self, chat_id: str, text: str) -> None:
        if chat_id in self.fail:
            raise TelegramError("Telegram rejected message: chat not found")
        self.sent.append((chat_id, text))


def test_periods() -> None:
    cal = get_work_calendar()
    assert period_for("weekly", DAY) == (date(2026, 10, 5), date(2026, 10, 11))
    assert period_for("monthly", DAY) == (date(2026, 10, 1), date(2026, 10, 31))
    # Monday is compared with Friday; the first day after the vacation with the last day before it
    assert previous_period("daily", date(2026, 10, 5), date(2026, 10, 5), cal) == (date(2026, 10, 2),) * 2
    assert previous_period("daily", date(2027, 1, 12), date(2027, 1, 12), cal) == (date(2026, 12, 25),) * 2
    assert previous_period("monthly", date(2026, 3, 1), date(2026, 3, 31), cal) == (date(2026, 2, 1), date(2026, 2, 28))
    # Monday's scheduled weekly report covers the previous Mon–Sun
    assert report_period_for_schedule("weekly", date(2026, 10, 12)) == (date(2026, 10, 5), date(2026, 10, 11))


async def _seed(session: AsyncSession) -> dict:
    pipe = CrmPipeline(bitrix_id=1, name="Сваи", sort=0)
    session.add(pipe)
    await session.flush()
    st = {
        c: CrmStage(bitrix_id=f"C1:{c}", pipeline_id=pipe.id, name=n, sort=o, semantics=m)
        for c, n, o, m in [
            ("NEW", "Не обработан", 10, "process"),
            ("TAKEN", "Взят в работу (до первого контакта)", 20, "process"),
            ("NODIAL", "Недозвон", 30, "process"),
            ("WON", "Сделка успешна", 90, "success"),
            ("LOSE", "Сделка провалена", 100, "failure"),
        ]
    }
    maria = CrmManager(bitrix_id=7, name="Мария", last_name="Иванова")
    idle = CrmManager(bitrix_id=8, name="Уволен", last_name="Давно")  # no deals → not in the report
    session.add_all([*st.values(), maria, idle])
    await session.flush()

    def deal(bid, stage, created, **kw):
        return CrmDeal(bitrix_id=bid, title=kw.pop("title", f"Сделка {bid}"), category_id=1, stage_id=st[stage].id,
                       assigned_by_id=maria.id, date_create=created, opportunity=Decimal(kw.pop("amount", "100000")), **kw)

    session.add_all(
        [
            deal(1, "WON", msk(10, 6, 10), closed=True, closedate=msk(10, 6, 15), amount="250000"),
            deal(2, "LOSE", msk(10, 6, 11), closed=True, closedate=msk(10, 6, 16)),
            deal(3, "NODIAL", msk(10, 6, 12), title="<Клиент> & Ко", has_future_activity=False, amount="900000"),
            deal(4, "NEW", msk(10, 5, 10), has_future_activity=True),  # created the previous workday
            DealStageHistory(bitrix_id=1, deal_bitrix_id=3, stage_bitrix_id="C1:NEW", category_id=1, created_time=msk(10, 6, 12)),
            DealStageHistory(bitrix_id=2, deal_bitrix_id=3, stage_bitrix_id="C1:TAKEN", category_id=1, created_time=msk(10, 6, 12, )),
            DealStageHistory(bitrix_id=3, deal_bitrix_id=3, stage_bitrix_id="C1:NODIAL", category_id=1, created_time=msk(10, 6, 13)),
            CrmActivity(bitrix_id=1, type_id=2, owner_type_id=2, owner_id=3, deadline=msk(10, 6, 14), completed=False),
            # Two more open overdue activities: a second one on deal 3 and one on the closed deal 2.
            # They count as overdue, but the share is about active deals with an overdue (1 of 2).
            CrmActivity(bitrix_id=2, type_id=3, owner_type_id=2, owner_id=3, deadline=msk(10, 1, 14), completed=False),
            CrmActivity(bitrix_id=3, type_id=3, owner_type_id=2, owner_id=2, deadline=msk(10, 1, 14), completed=False),
        ]
    )
    await session.commit()
    return {"maria": maria}


@pytest.mark.asyncio
async def test_daily_report_content(db_session: AsyncSession) -> None:
    await _seed(db_session)
    data = await build_report(db_session, "daily", DAY, DAY)
    m = data["metrics"]
    assert (m["new"], m["won"], m["lost"], m["overdue"]) == (3, 1, 1, 1)
    assert m["won_sum"] == 250000.0 and m["overdue_open_now"] == 3
    assert m["stuck_now"] == 2  # «Недозвон» since October and «Не обработан» for a month
    assert data["previous"]["period_start"] == "2026-10-05" and data["previous"]["new"] == 1
    assert [r["name"] for r in data["managers"]] == ["Иванова Мария"]
    row = data["managers"][0]
    assert (row["new"], row["won"], row["lost"], row["overdue"], row["overdue_open"], row["active"]) == (3, 1, 1, 1, 3, 2)
    assert row["overdue_deals"] == 1 and row["overdue_share"] == 50.0  # never above 100 %
    assert data["problem_stages"] == []
    assert data["card_quality"]["no_next_activity"] == 1
    assert data["card_quality"]["deals"][0]["bitrix_id"] == 3

    text = render_report(data)
    assert text.startswith("<b>Итоги дня · 06.10.2026</b>")
    assert "Новых сделок: 3 <i>(было 1)</i>" in text
    assert "Успешно закрыто: 1 на 250 000 ₽" in text
    assert "&lt;Клиент&gt; &amp; Ко" in text and "<Клиент>" not in text
    assert "Иванова Мария — новых 3 · выиграно 1 · проиграно 1 · просрочек 1 · висит 3 · зависло 2" in text
    assert "Проблемные этапы" not in text  # weekly/monthly only


@pytest.mark.asyncio
async def test_weekly_report_has_problem_stages(db_session: AsyncSession) -> None:
    await _seed(db_session)
    start, end = period_for("weekly", DAY)
    text = render_report(await build_report(db_session, "weekly", start, end))
    assert text.startswith("<b>Итоги недели · 05.10–11.10.2026</b>")
    assert "<b>Проблемные этапы</b>" in text and "Недозвон — зависло 1 из 1 · просрочек 1" in text


@pytest.mark.asyncio
async def test_scheduled_report_archived_sent_once(db_session: AsyncSession, monkeypatch) -> None:
    await _seed(db_session)
    s = get_settings()
    monkeypatch.setattr(s, "TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setattr(s, "TELEGRAM_REPORT_CHAT_IDS", "111, 222")
    tg = RecordingTelegram(fail={"222"})

    first = await run_scheduled_report(db_session, "daily", today=DAY, client=tg)  # type: ignore[arg-type]
    assert first["status"] == "sent" and first["sent_to"] == 1 and len(first["errors"]) == 1
    assert [c for c, _ in tg.sent] == ["111"]
    report = await db_session.get(SalesReport, first["report_id"])
    assert report.sent_at is not None and "222" in (report.send_error or "")

    again = await run_scheduled_report(db_session, "daily", today=DAY, client=tg)  # type: ignore[arg-type]
    assert again["reason"] == "already_sent" and len(tg.sent) == 1
    count = (await db_session.execute(select(func.count()).select_from(SalesReport))).scalar_one()
    assert count == 1  # regenerated in place, not duplicated

    weekend = await run_scheduled_report(db_session, "daily", today=date(2026, 10, 10), client=tg)  # type: ignore[arg-type]
    assert weekend["reason"] == "not_a_workday"
    vacation = await run_scheduled_report(db_session, "daily", today=date(2026, 12, 29), client=tg)  # type: ignore[arg-type]
    assert vacation["reason"] == "not_a_workday"


@pytest.mark.asyncio
async def test_report_archived_without_telegram(db_session: AsyncSession, monkeypatch) -> None:
    await _seed(db_session)
    monkeypatch.setattr(get_settings(), "TELEGRAM_BOT_TOKEN", "")
    r = await run_scheduled_report(db_session, "weekly", today=date(2026, 10, 12))
    assert r["reason"] == "telegram_not_configured"
    report = await db_session.get(SalesReport, r["report_id"])
    assert (report.kind, report.period_start, report.period_end) == ("weekly", date(2026, 10, 5), date(2026, 10, 11))
    assert report.sent_at is None and report.text.startswith("<b>Итоги недели")


async def _login(client: AsyncClient, session: AsyncSession, role: UserRole) -> dict:
    email = f"{role.value}-rep@ex.com"
    session.add(User(email=email, password_hash=hash_password("password123"), role=role, is_active=True))
    await session.commit()
    await client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return {"X-CSRF-Token": client.cookies.get("focus_csrf") or ""}


@pytest.mark.asyncio
async def test_archive_api(client: AsyncClient, db_session: AsyncSession, monkeypatch) -> None:
    await _seed(db_session)
    monkeypatch.setattr(get_settings(), "TELEGRAM_BOT_TOKEN", "")
    headers = await _login(client, db_session, UserRole.viewer)
    assert (await client.post("/api/v1/reports/archive/generate", json={"kind": "daily"}, headers=headers)).status_code == 403

    client.cookies.clear()
    headers = await _login(client, db_session, UserRole.admin)
    assert (await client.post("/api/v1/reports/archive/generate", json={"kind": "daily"})).status_code == 403  # no CSRF
    future = (date.today() + timedelta(days=40)).isoformat()
    assert (await client.post("/api/v1/reports/archive/generate", json={"kind": "daily", "day": future}, headers=headers)).status_code == 422
    made = await client.post("/api/v1/reports/archive/generate", json={"kind": "monthly", "day": "2026-10-15"}, headers=headers)
    assert made.status_code == 200 and made.json()["title"] == "Итоги месяца · октябрь 2026"
    rid = made.json()["id"]

    listing = (await client.get("/api/v1/reports/archive")).json()
    assert [i["id"] for i in listing["items"]] == [rid] and listing["schedule"]["daily_time"] == "20:00"
    detail = (await client.get(f"/api/v1/reports/archive/{rid}")).json()
    assert "Итоги месяца" in detail["text"] and "<b>" not in detail["text"]
    assert detail["data"]["metrics"]["new"] == 4
    sent = (await client.post(f"/api/v1/reports/archive/{rid}/send", headers=headers)).json()
    assert sent["reason"] == "telegram_not_configured"
    assert (await client.get("/api/v1/reports/archive/999")).status_code == 404

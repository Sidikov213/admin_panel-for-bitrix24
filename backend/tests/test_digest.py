"""Daily Telegram digest: content, rendering, delivery, dedupe, API permissions."""

import json
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password
from app.core.config import get_settings
from app.core.timezone import utc_now
from app.models.auth import User, UserRole
from app.models.crm import CrmActivity, CrmDeal, CrmManager, CrmPipeline, CrmStage
from app.notifications.digest import build_digest, render_manager_digest, render_team_digest, to_plain_text
from app.notifications.service import send_daily_digest
from app.notifications.telegram import TelegramClient, TelegramError, split_message

TOKEN = "123456:TEST-token"


class RecordingTelegram:
    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail_for = fail_for or set()

    async def send_message(self, chat_id: str, text: str) -> None:
        if chat_id in self.fail_for:
            raise TelegramError("Telegram rejected message: chat not found")
        self.sent.append((chat_id, text))


@pytest.fixture
def telegram_settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(s, "TELEGRAM_CHAT_ID", "-100777")
    monkeypatch.setattr(s, "BITRIX_PORTAL_URL", "https://portal.example")
    monkeypatch.setattr(s, "DIGEST_STALE_DAYS", 7)
    return s


async def _seed(session: AsyncSession) -> dict:
    now = utc_now()
    pipe = CrmPipeline(bitrix_id=1, name="P", sort=0)
    session.add(pipe)
    await session.flush()
    won = CrmStage(bitrix_id="C1:WON", pipeline_id=pipe.id, name="Won", sort=9, semantics="success")
    work = CrmStage(bitrix_id="C1:NEW", pipeline_id=pipe.id, name="New", sort=1, semantics="process")
    ivan = CrmManager(bitrix_id=7, name="Иван", last_name="Петров", telegram_chat_id="555")
    olga = CrmManager(bitrix_id=8, name="Ольга", last_name="Смирнова")
    session.add_all([won, work, ivan, olga])
    await session.flush()
    deals = {
        # No next activity, big amount, title needs HTML escaping
        "no_future": CrmDeal(
            bitrix_id=101, title="Сваи <ООО «Рога»> & Ко", category_id=1, stage_id=work.id,
            assigned_by_id=ivan.id, opportunity=Decimal("1200000"), closed=False,
            has_future_activity=False, date_modify=now - timedelta(days=1),
        ),
        # Has next activity but nothing moved for 12 days
        "idle": CrmDeal(
            bitrix_id=102, title="Долгая сделка", category_id=1, stage_id=work.id,
            assigned_by_id=ivan.id, opportunity=Decimal("50000"), closed=False,
            has_future_activity=True, date_modify=now - timedelta(days=12),
        ),
        # Healthy deal of another manager
        "ok": CrmDeal(
            bitrix_id=103, title="Нормальная", category_id=1, stage_id=work.id,
            assigned_by_id=olga.id, closed=False, has_future_activity=True, date_modify=now,
        ),
        "won": CrmDeal(
            bitrix_id=104, title="Выиграна", category_id=1, stage_id=won.id, assigned_by_id=olga.id,
            opportunity=Decimal("300000"), closed=True, closedate=now - timedelta(days=1),
            date_create=now - timedelta(days=1),
        ),
    }
    session.add_all(deals.values())
    session.add_all(
        [
            CrmActivity(bitrix_id=1, owner_type_id=2, owner_id=102, deadline=now - timedelta(days=2), completed=False),
            CrmActivity(bitrix_id=2, owner_type_id=2, owner_id=102, deadline=now + timedelta(days=2), completed=False),
        ]
    )
    await session.commit()
    return {"ivan": ivan, "olga": olga, **deals}


@pytest.mark.asyncio
async def test_build_digest_counts_and_ranking(db_session: AsyncSession, telegram_settings) -> None:
    seeded = await _seed(db_session)
    digest = await build_digest(db_session)

    assert digest.active_deals == 3
    assert digest.overdue_activities == 1
    assert digest.no_future_count == 1
    assert digest.idle_count == 1
    assert digest.won_yesterday == 1
    assert [m.manager_id for m in digest.managers] == [seeded["ivan"].id]  # Olga has no problems
    ivan = digest.managers[0]
    assert ivan.overdue_activities == 1
    assert [d.bitrix_id for d in ivan.no_future] == [101]
    assert [d.bitrix_id for d in ivan.idle] == [102]
    assert ivan.idle[0].idle_days == 12


@pytest.mark.asyncio
async def test_rendering_escapes_and_links(db_session: AsyncSession, telegram_settings) -> None:
    await _seed(db_session)
    digest = await build_digest(db_session)
    team = render_team_digest(digest)
    personal = render_manager_digest(digest, digest.managers[0])

    assert "<ООО" not in team and "<ООО" not in personal
    assert "&lt;ООО «Рога»&gt; &amp; Ко" in personal
    assert '<a href="https://portal.example/crm/deal/details/101/">' in personal
    assert "1 200 000 ₽" in personal
    assert "Петров Иван — просрочено 1 · без дела 1 · стоят 1" in team
    assert "выиграно 1 на 300 000 ₽" in team
    plain = to_plain_text(personal)
    assert "<a" not in plain and "Сваи <ООО «Рога»> & Ко" in plain


def test_split_message_keeps_lines_whole() -> None:
    lines = [f"<b>line {i}</b> " + "x" * 50 for i in range(200)]
    chunks = split_message("\n".join(lines), limit=1000)
    assert all(len(c) <= 1000 for c in chunks)
    assert "\n".join(chunks).split("\n") == lines
    assert all(c.count("<b>") == c.count("</b>") for c in chunks)


@pytest.mark.asyncio
async def test_telegram_client_posts_and_hides_token_on_error() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append({"url": str(request.url), **body})
        if body["chat_id"] == "bad":
            return httpx.Response(400, json={"ok": False, "description": f"chat not found for {TOKEN}"})
        return httpx.Response(200, json={"ok": True, "result": {}})

    client = TelegramClient(TOKEN, transport=httpx.MockTransport(handler))
    await client.send_message("42", "<b>hi</b>")
    assert calls[0]["url"] == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert calls[0]["parse_mode"] == "HTML" and calls[0]["chat_id"] == "42"

    with pytest.raises(TelegramError) as exc:
        await client.send_message("bad", "x")
    assert TOKEN not in str(exc.value) and "chat not found" in str(exc.value)


@pytest.mark.asyncio
async def test_send_digest_skipped_without_token(db_session: AsyncSession, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "TELEGRAM_BOT_TOKEN", "")
    result = await send_daily_digest(db_session, client=RecordingTelegram())  # type: ignore[arg-type]
    assert result == {"status": "skipped", "reason": "telegram_not_configured"}


@pytest.mark.asyncio
async def test_send_digest_once_per_day_and_force(db_session: AsyncSession, telegram_settings) -> None:
    await _seed(db_session)
    tg = RecordingTelegram()

    first = await send_daily_digest(db_session, client=tg)  # type: ignore[arg-type]
    assert first["status"] == "sent" and first["team_sent"] is True and first["managers_sent"] == 1
    assert [chat for chat, _ in tg.sent] == ["-100777", "555"]

    second = await send_daily_digest(db_session, client=tg)  # type: ignore[arg-type]
    assert second["reason"] == "already_sent_today"
    assert len(tg.sent) == 2

    forced = await send_daily_digest(db_session, force=True, client=tg)  # type: ignore[arg-type]
    assert forced["status"] == "sent" and len(tg.sent) == 4


@pytest.mark.asyncio
async def test_one_failed_recipient_does_not_block_others(db_session: AsyncSession, telegram_settings) -> None:
    await _seed(db_session)
    tg = RecordingTelegram(fail_for={"-100777"})
    result = await send_daily_digest(db_session, client=tg)  # type: ignore[arg-type]
    assert result["status"] == "sent"
    assert result["team_sent"] is False and result["managers_sent"] == 1
    assert len(result["errors"]) == 1


async def _login(client: AsyncClient, session: AsyncSession, role: UserRole) -> str:
    email = f"{role.value}@ex.com"
    session.add(User(email=email, password_hash=hash_password("password123"), role=role, is_active=True))
    await session.commit()
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200
    return client.cookies.get("focus_csrf") or ""


@pytest.mark.asyncio
async def test_preview_and_send_are_admin_only(client: AsyncClient, db_session: AsyncSession, telegram_settings) -> None:
    await _seed(db_session)
    csrf = await _login(client, db_session, UserRole.viewer)
    assert (await client.get("/api/v1/notifications/status")).status_code == 200
    assert (await client.get("/api/v1/notifications/digest/preview")).status_code == 403
    sent = await client.post("/api/v1/notifications/digest/send", headers={"X-CSRF-Token": csrf})
    assert sent.status_code == 403


@pytest.mark.asyncio
async def test_preview_returns_plain_text(client: AsyncClient, db_session: AsyncSession, telegram_settings) -> None:
    await _seed(db_session)
    await _login(client, db_session, UserRole.admin)
    r = await client.get("/api/v1/notifications/digest/preview")
    assert r.status_code == 200
    data = r.json()
    assert "Дайджест отдела продаж" in data["team"] and "<b>" not in data["team"]
    assert [m["has_chat"] for m in data["managers"]] == [True]

    status_ = (await client.get("/api/v1/notifications/status")).json()
    assert status_["telegram_configured"] is True and status_["managers_with_chat"] == 1


@pytest.mark.asyncio
async def test_set_manager_chat_id(client: AsyncClient, db_session: AsyncSession) -> None:
    mgr = CrmManager(bitrix_id=9, name="A", last_name="B")
    db_session.add(mgr)
    await db_session.commit()
    csrf = await _login(client, db_session, UserRole.admin)
    url = f"/api/v1/managers/{mgr.id}"

    assert (await client.patch(url, json={"telegram_chat_id": "123"})).status_code == 403  # no CSRF
    bad = await client.patch(url, json={"telegram_chat_id": "not a chat"}, headers={"X-CSRF-Token": csrf})
    assert bad.status_code == 422
    ok = await client.patch(url, json={"telegram_chat_id": " -100123 "}, headers={"X-CSRF-Token": csrf})
    assert ok.status_code == 200 and ok.json()["telegram_chat_id"] == "-100123"
    cleared = await client.patch(url, json={"telegram_chat_id": ""}, headers={"X-CSRF-Token": csrf})
    assert cleared.json()["telegram_chat_id"] is None

"""Avito: config, read-only client, dialog sync, deal linking, reply-speed analytics, API."""

import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.avito import avito_summary
from app.auth.password import hash_password
from app.core.config import Settings, get_settings
from app.integrations.avito.client import AvitoClient, AvitoError
from app.integrations.avito.sync import link_deals, run_avito_sync, sync_account
from app.models.auth import User, UserRole
from app.models.avito import AvitoChat, AvitoMessage
from app.models.crm import CrmDeal, CrmPipeline, CrmStage, DealComment
from app.models.sync import SyncRun, SyncStatus, SyncType

MSK = ZoneInfo("Europe/Moscow")
ACC = {"id": 310437658, "name": "Линия Авитологи", "client_id": "cid", "client_secret": "TOP-SECRET-123"}


def ts(mo: int, d: int, h: int, mi: int = 0) -> int:
    return int(datetime(2026, mo, d, h, mi, tzinfo=MSK).timestamp())


# --- config --------------------------------------------------------------------------


def test_accounts_config_parsing() -> None:
    s = Settings(AVITO_ACCOUNTS=json.dumps([ACC, {**ACC, "id": "411864664", "name": ""}]))
    assert [a["id"] for a in s.avito_accounts] == [310437658, 411864664]
    assert s.avito_accounts[1]["name"] == "411864664"
    assert Settings(AVITO_ACCOUNTS="").avito_accounts == []
    with pytest.raises(ValueError):
        _ = Settings(AVITO_ACCOUNTS="not json").avito_accounts
    with pytest.raises(ValueError):
        _ = Settings(AVITO_ACCOUNTS=json.dumps([{"id": 1, "client_id": "x"}])).avito_accounts


# --- client --------------------------------------------------------------------------


def _client(handler) -> AvitoClient:
    return AvitoClient(ACC, transport=httpx.MockTransport(handler), rate_limit_rps=0, max_retries=3)


@pytest.mark.asyncio
async def test_client_token_bearer_and_refresh() -> None:
    calls: list[str] = []
    tokens = iter(["t1", "t2"])

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/token":
            form = dict(x.split("=") for x in request.content.decode().split("&"))
            assert form["grant_type"] == "client_credentials" and form["client_id"] == "cid"
            return httpx.Response(200, json={"access_token": next(tokens), "expires_in": 86400})
        auth = request.headers["Authorization"]
        if auth == "Bearer t1" and len([c for c in calls if "chats" in c]) == 2:
            return httpx.Response(401, json={})  # token revoked → client gets a new one
        return httpx.Response(200, json={"chats": [{"id": "u2i-abc123"}]})

    client = _client(handler)
    assert (await client.list_chats())[0]["id"] == "u2i-abc123"
    assert (await client.list_chats())[0]["id"] == "u2i-abc123"
    assert calls == [
        "POST /token", "GET /messenger/v2/accounts/310437658/chats",
        "GET /messenger/v2/accounts/310437658/chats", "POST /token", "GET /messenger/v2/accounts/310437658/chats",
    ]


@pytest.mark.asyncio
async def test_client_is_read_only_and_hides_secrets() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(400, json={"error": "invalid_client", "client_secret": ACC["client_secret"]})
        raise AssertionError("no request expected")

    client = _client(handler)
    for path in ("/messenger/v1/accounts/310437658/chats/u2i-x/messages", "/messenger/v1/accounts/310437658/chats/u2i-x/read",
                 "/core/v1/items"):
        with pytest.raises(AvitoError) as exc:
            await client.get(path)
        assert exc.value.kind == "forbidden_path"
    with pytest.raises(AvitoError) as exc:
        await client.list_chats()
    assert exc.value.kind == "invalid_credentials" and ACC["client_secret"] not in str(exc.value)


@pytest.mark.asyncio
async def test_client_403_explains_missing_access() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(403, json={})

    with pytest.raises(AvitoError) as exc:
        await _client(handler).list_messages("u2i-abc123")
    assert exc.value.kind == "forbidden" and "tariff" in str(exc.value)


# --- sync ----------------------------------------------------------------------------


class FakeAvito:
    account_id = ACC["id"]

    def __init__(self, chats, messages) -> None:
        self.chats, self.messages, self.message_calls = chats, messages, 0

    async def list_chats(self, *, offset=0, limit=100):
        return self.chats[offset : offset + limit]

    async def list_messages(self, chat_id, *, offset=0, limit=100):
        self.message_calls += 1
        msgs = sorted(self.messages.get(chat_id, []), key=lambda m: -m["created"])  # newest first, as Avito
        return msgs[offset : offset + limit]


def _chat(cid, updated, item=(1001, "Сваи под ключ"), client=("555", "Иван")):
    return {"id": cid, "created": updated - 3600, "updated": updated,
            "context": {"type": "item", "value": {"id": item[0], "title": item[1], "url": f"https://avito.ru/{item[0]}"}},
            "users": [{"id": ACC["id"], "name": "Мы"}, {"id": client[0], "name": client[1]}]}


def _msg(mid, created, direction, text="текст", mtype="text"):
    return {"id": mid, "created": created, "direction": direction, "type": mtype,
            "author_id": ACC["id"] if direction == "out" else 555, "content": {"text": text}}


CHATS = [_chat("u2i-fast00001", ts(11, 9, 11)), _chat("u2i-slow00002", ts(11, 9, 10), item=(1002, "Винтовые сваи")),
         _chat("u2i-wait00003", ts(11, 9, 9), client=("777", "Пётр"))]
MESSAGES = {
    # Client at 10:00, auto-reply (system) at once, manager at 10:20 → 20 working minutes
    "u2i-fast00001": [_msg("m1", ts(11, 9, 10), "in", "Сколько стоит?"), _msg("m2", ts(11, 9, 10), "out", "Автоответ", "system"),
                      _msg("m3", ts(11, 9, 10, 20), "out", "Здравствуйте!")],
    # Friday 16:30 → Monday 09:45: 30 + 45 = 75 working minutes → late (norm 30)
    "u2i-slow00002": [_msg("m4", ts(11, 6, 16, 30), "in", "Нужны сваи"), _msg("m5", ts(11, 9, 9, 45), "out", "Добрый день")],
    # Waiting since Monday 09:00
    "u2i-wait00003": [_msg("m6", ts(11, 9, 9), "in", "Ау?")],
}


@pytest.mark.asyncio
async def test_sync_derives_first_reply_and_is_incremental(db_session: AsyncSession) -> None:
    fake = FakeAvito(CHATS, MESSAGES)
    since = datetime(2026, 11, 1, tzinfo=timezone.utc)
    counts = await sync_account(db_session, fake, since=since)  # type: ignore[arg-type]
    await db_session.commit()
    assert counts == {"chats": 3, "messages": 6}
    fast = (await db_session.execute(select(AvitoChat).where(AvitoChat.chat_id == "u2i-fast00001"))).scalar_one()
    assert fast.client_name == "Иван" and fast.item_title == "Сваи под ключ"
    assert fast.first_reply_at.replace(tzinfo=timezone.utc).timestamp() == ts(11, 9, 10, 20)  # auto-reply ignored
    assert fast.messages_count == 2 and fast.last_direction == "out"

    MESSAGES["u2i-wait00003"].append(_msg("m7", ts(11, 9, 12), "out", "Слушаю"))
    again = await sync_account(db_session, fake, since=since)  # type: ignore[arg-type]
    assert again["messages"] == 1  # only the new one; pages stop at known messages
    total = (await db_session.execute(select(func.count()).select_from(AvitoMessage))).scalar_one()
    assert total == 7
    MESSAGES["u2i-wait00003"].pop()

    late = await sync_account(db_session, fake, since=datetime(2026, 11, 9, 7, 30, tzinfo=timezone.utc))  # type: ignore[arg-type]
    assert late["chats"] == 1  # only the chat updated after `since` is refetched


@pytest.mark.asyncio
async def test_link_deals_by_chat_link_in_field_or_comment(db_session: AsyncSession) -> None:
    await sync_account(db_session, FakeAvito(CHATS, MESSAGES), since=datetime(2026, 11, 1, tzinfo=timezone.utc))  # type: ignore[arg-type]
    db_session.add_all(
        [
            CrmDeal(bitrix_id=50, title="Иван С30.20", raw={"UF_CRM_CHAT": "https://www.avito.ru/profile/messenger/channel/u2i-fast00001"}),
            CrmDeal(bitrix_id=51, title="x", raw={"UF_CRM_CHAT": ""}),
            DealComment(bitrix_id=1, deal_bitrix_id=51, created=datetime(2026, 11, 9, tzinfo=timezone.utc),
                        text="Переписка в Авито: u2i-slow00002"),
        ]
    )
    await db_session.commit()
    assert await link_deals(db_session) == 2
    links = dict((await db_session.execute(select(AvitoChat.chat_id, AvitoChat.deal_link_source))).all())
    assert links == {"u2i-fast00001": "deal_field", "u2i-slow00002": "comment", "u2i-wait00003": None}


@pytest.mark.asyncio
async def test_summary_reply_speed_unanswered_items(db_session: AsyncSession, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "AVITO_ACCOUNTS", json.dumps([ACC]))
    await sync_account(db_session, FakeAvito(CHATS, MESSAGES), since=datetime(2026, 11, 1, tzinfo=timezone.utc))  # type: ignore[arg-type]
    pipe = CrmPipeline(bitrix_id=1, name="Сваи", sort=0)
    db_session.add(pipe)
    await db_session.flush()
    won = CrmStage(bitrix_id="C1:WON", pipeline_id=pipe.id, name="Успешно", sort=90, semantics="success")
    db_session.add(won)
    await db_session.flush()
    db_session.add(CrmDeal(bitrix_id=50, title="Иван", stage_id=won.id, closed=True,
                           raw={"x": "u2i-fast00001"}))
    await db_session.commit()
    await link_deals(db_session)
    await db_session.commit()

    now = datetime(2026, 11, 9, 12, tzinfo=MSK).astimezone(timezone.utc)
    r = await avito_summary(db_session, period_start=date(2026, 11, 2), period_end=date(2026, 11, 9), now=now)
    rows = {x["chat_id"]: x for x in r["slowest"]}
    assert rows["u2i-fast00001"]["reply_seconds"] == 20 * 60 and not rows["u2i-fast00001"]["late"]
    assert rows["u2i-slow00002"]["reply_seconds"] == 75 * 60 and rows["u2i-slow00002"]["late"]
    assert rows["u2i-wait00003"]["waiting_seconds"] == 3 * 3600 and rows["u2i-wait00003"]["late"]
    s = r["summary"]
    assert (s["new"], s["replied"], s["no_reply"], s["late"], s["unanswered_now"]) == (3, 2, 1, 2, 1)
    assert (s["linked"], s["won"]) == (1, 1)
    assert r["unanswered"][0]["client_name"] == "Пётр"
    assert r["unanswered"][0]["chat_url"] == "https://www.avito.ru/profile/messenger/channel/u2i-wait00003"
    assert r["by_account"][0]["name"] == "Линия Авитологи"
    assert {i["title"]: i["new"] for i in r["by_item"]} == {"Сваи под ключ": 2, "Винтовые сваи": 1}


@pytest.mark.asyncio
async def test_run_sync_isolates_failing_account(db_session: AsyncSession) -> None:
    ok_acc, bad_acc = ACC, {**ACC, "id": 411864664, "name": "Забей сваю"}

    def factory(acc):
        if acc["id"] == bad_acc["id"]:
            bad = AsyncMock()
            bad.account_id = acc["id"]
            bad.list_chats.side_effect = AvitoError("HTTP 403: no access", kind="forbidden")
            return bad
        return FakeAvito(CHATS, MESSAGES)

    from app.repositories.sync import SyncRepository

    SyncRepository.try_advisory_lock = AsyncMock(return_value=True)  # type: ignore[method-assign]
    SyncRepository.advisory_unlock = AsyncMock()  # type: ignore[method-assign]
    try:
        r = await run_avito_sync(db_session, accounts=[ok_acc, bad_acc], client_factory=factory)
    finally:
        del SyncRepository.try_advisory_lock, SyncRepository.advisory_unlock
    assert r["accounts"][str(ok_acc["id"])]["chats"] == 3
    assert r["accounts"][str(bad_acc["id"])]["kind"] == "forbidden" and len(r["errors"]) == 1
    run = (await db_session.execute(select(SyncRun).where(SyncRun.sync_type == SyncType.avito))).scalar_one()
    assert run.status == SyncStatus.success and run.errors_count == 1
    assert (await run_avito_sync(db_session, accounts=[]))["reason"] == "not_configured"


# --- API -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_never_returns_secrets(client: AsyncClient, db_session: AsyncSession, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "AVITO_ACCOUNTS", json.dumps([ACC]))
    await sync_account(db_session, FakeAvito(CHATS, MESSAGES), since=datetime(2026, 11, 1, tzinfo=timezone.utc))  # type: ignore[arg-type]
    db_session.add(User(email="v@ex.com", password_hash=hash_password("password123"), role=UserRole.viewer, is_active=True))
    await db_session.commit()
    assert (await client.get("/api/v1/avito/status")).status_code == 401
    await client.post("/api/v1/auth/login", json={"email": "v@ex.com", "password": "password123"})

    st = await client.get("/api/v1/avito/status")
    assert st.status_code == 200 and st.json()["accounts"][0]["name"] == "Линия Авитологи"
    assert "TOP-SECRET" not in st.text and "cid" not in st.text
    assert (await client.get("/api/v1/avito/summary", params={"period_start": "2026-11-01", "period_end": "2026-11-09"})).status_code == 200
    chat = (await client.get("/api/v1/avito/chats/u2i-fast00001")).json()
    assert [m["text"] for m in chat["messages"]] == ["Сколько стоит?", "Автоответ", "Здравствуйте!"]
    assert chat["messages"][1]["is_system"] is True
    assert (await client.get("/api/v1/avito/chats/u2i-nope")).status_code == 404

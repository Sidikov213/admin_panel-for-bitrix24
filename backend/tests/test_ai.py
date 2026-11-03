"""AI conclusions: what leaves the server, caching and limits, reports, the Claude call itself, API."""

import json
from datetime import date

import anthropic
import httpx2
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_reports import DAY, _login, _seed, msk

import app.ai.service as ai_service
from app.ai.privacy import restore, scrub
from app.ai.provider import FALLBACK_BETA, AIError, AIProvider, AIResult, ClaudeProvider
from app.ai.schemas import Communication, ManagerFinding, PeriodAnalysis, RepeatedProblem
from app.ai.service import analyze_period, present
from app.core.config import get_settings
from app.models.analytics import AIAnalysis, SalesReport
from app.models.auth import UserRole
from app.models.crm import DealComment
from app.reports.service import generate_report


def answer(manager: str) -> PeriodAnalysis:
    return PeriodAnalysis(
        headline=f"{manager} закрыл 1 сделку на 250 000 ₽, но 3 дела висят просроченными.",
        department=["Новых сделок 3 против 1 в прошлый день.", "Выиграна 1 сделка.", "Просрочек 1.", "Лишний пункт."],
        risks=["Сделка №3 без следующего дела."],
        managers=[ManagerFinding(manager=manager, summary="Много новых, просрочки копятся.", strengths=["3 новых"],
                                 problems=["3 открытые просрочки"], actions=["Закрыть просрочки до 12:00"])],
        repeated_problems=[RepeatedProblem(problem="Просрочки", who=[manager], evidence="overdue_open 3")],
        communication=Communication(assessed=False, comments=[], avito_replies=[], script=[], examples=[]),
        recommendations=[f"Разобрать с {manager} просрочки", "Поставить следующее дело по №3"],
    )


class FakeProvider(AIProvider):
    def __init__(self, manager: str = "", fail: AIError | None = None) -> None:
        self.calls: list[dict] = []
        self.manager, self.fail = manager, fail

    async def complete(self, *, system, prompt, schema):
        self.calls.append({"system": system, "prompt": prompt})
        if self.fail:
            raise self.fail
        data = json.loads(prompt.split("<data>\n", 1)[1].rsplit("\n</data>", 1)[0])
        return AIResult(output=answer(self.manager or data["managers"][0]["manager"]), model="claude-opus-5-5",
                        input_tokens=1200, output_tokens=800)


def sent_data(provider: FakeProvider, i: int = -1) -> dict:
    return json.loads(provider.calls[i]["prompt"].split("<data>\n", 1)[1].rsplit("\n</data>", 1)[0])


def test_scrub_and_restore() -> None:
    t = scrub("Позвонить +7 (915) 123-45-67 или ivan.petrov@mail.ru, смета https://disk.yandex.ru/x тг @ivan_svai. Сумма 12 500 000 ₽")
    assert "915" not in t and "mail.ru" not in t and "yandex" not in t and "ivan_svai" not in t
    assert "[телефон]" in t and "[email]" in t and "[ссылка]" in t and "12 500 000 ₽" in t
    assert scrub("а" * 700).endswith("…") and len(scrub("а" * 700)) == 600
    names = {"Менеджер-5": "Иванова Мария"}
    assert restore({"x": ["Менеджер-5 и Менеджер-6"]}, names) == {"x": ["Иванова Мария и Менеджер-6"]}


@pytest.mark.asyncio
async def test_only_numbers_leave_by_default(db_session: AsyncSession, monkeypatch) -> None:
    seeded = await _seed(db_session)
    mid = seeded["maria"].id
    db_session.add(DealComment(bitrix_id=1, deal_bitrix_id=3, created=msk(10, 6, 13), text="Клиент Петров +79151234567"))
    await db_session.commit()
    monkeypatch.setattr(get_settings(), "AI_SEND_TEXTS", False)
    fake = FakeProvider()

    row = await analyze_period(db_session, "daily", DAY, DAY, provider=fake)
    assert row.status == "ok" and row.input_tokens == 1200 and row.texts_sent is False
    prompt = fake.calls[0]["prompt"]
    # No names, no deal titles, no comments, no links
    for leak in ("Иванова", "Мария", "Клиент", "Петров", "79151234567", "http"):
        assert leak not in prompt, leak
    data = sent_data(fake)
    assert data["managers"][0]["manager"] == f"Менеджер-{mid}"
    assert data["department"]["new"] == 3 and data["previous_period"]["new"] == 1
    assert "texts" not in data and "reaction_median_seconds" not in data["department"]
    # Stored aliased; shown with the real name
    assert f"Менеджер-{mid}" in json.dumps(row.result, ensure_ascii=False)
    shown = await present(db_session, row, with_context=True)
    assert shown["result"]["managers"][0]["manager"] == "Иванова Мария"
    assert shown["headline"].startswith("Иванова Мария закрыл")
    assert shown["context"]["managers"][0]["manager"] == f"Менеджер-{mid}"


@pytest.mark.asyncio
async def test_texts_only_when_enabled_and_scrubbed(db_session: AsyncSession, monkeypatch) -> None:
    await _seed(db_session)
    db_session.add(DealComment(bitrix_id=1, deal_bitrix_id=3, created=msk(10, 6, 13),
                               text="06.10 Цель: замер. Итог: недозвон +7 915 123 45 67. Следующий шаг: перезвонить"))
    await db_session.commit()
    monkeypatch.setattr(get_settings(), "AI_SEND_TEXTS", True)
    fake = FakeProvider()
    row = await analyze_period(db_session, "daily", DAY, DAY, provider=fake)
    texts = sent_data(fake)["texts"]
    assert row.texts_sent is True and len(texts["comments"]) == 1
    c = texts["comments"][0]
    assert c["deal"] == "№3" and c["stage"] == "Недозвон" and "[телефон]" in c["text"] and "915" not in c["text"]
    assert texts["avito_dialogs"] == []


@pytest.mark.asyncio
async def test_cache_force_history_and_limit(db_session: AsyncSession, monkeypatch) -> None:
    await _seed(db_session)
    fake = FakeProvider()
    first = await analyze_period(db_session, "daily", DAY, DAY, provider=fake)
    again = await analyze_period(db_session, "daily", DAY, DAY, provider=fake)
    assert again.id == first.id and len(fake.calls) == 1  # same numbers → no second call
    forced = await analyze_period(db_session, "daily", DAY, DAY, provider=fake, force=True)
    assert forced.id != first.id and len(fake.calls) == 2

    # The next day sees the previous conclusions (repeated problems)
    nxt = date(2026, 10, 7)
    await analyze_period(db_session, "daily", nxt, nxt, provider=fake)
    hist = sent_data(fake)["previous_ai_findings"]
    assert len(hist) == 1 and hist[0]["period"] == "2026-10-06..2026-10-06" and hist[0]["repeated_problems"] == ["Просрочки"]

    monkeypatch.setattr(get_settings(), "AI_DAILY_LIMIT", 3)
    with pytest.raises(AIError) as e:
        await analyze_period(db_session, "weekly", date(2026, 10, 5), date(2026, 10, 11), provider=fake)
    assert e.value.kind == "limit" and len(fake.calls) == 3

    monkeypatch.setattr(get_settings(), "AI_DAILY_LIMIT", 30)
    failing = FakeProvider(fail=AIError("Anthropic недоступен", "unavailable"))
    with pytest.raises(AIError):
        await analyze_period(db_session, "monthly", date(2026, 10, 1), date(2026, 10, 31), provider=failing)
    err = (await db_session.execute(select(AIAnalysis).where(AIAnalysis.kind == "monthly"))).scalar_one()
    assert err.status == "error" and err.result is None and "недоступен" in err.error

    monkeypatch.setattr(get_settings(), "ANTHROPIC_API_KEY", "")
    with pytest.raises(AIError) as e:
        await analyze_period(db_session, "daily", DAY, DAY)
    assert e.value.kind == "not_configured"


@pytest.mark.asyncio
async def test_report_gets_ai_conclusion(db_session: AsyncSession, monkeypatch) -> None:
    await _seed(db_session)
    s = get_settings()
    monkeypatch.setattr(s, "ANTHROPIC_API_KEY", "sk-test")
    fake = FakeProvider()
    monkeypatch.setattr(ai_service, "ClaudeProvider", lambda: fake)

    report = await generate_report(db_session, "daily", DAY, DAY)
    ai = report.data["ai_summary"]
    assert ai["status"] == "ok" and len(ai["points"]) == 3 and ai["headline"].startswith("Иванова Мария")
    assert "<b>Вывод ИИ</b>" in report.text and "1. Разобрать с Иванова Мария просрочки" in report.text
    assert (await db_session.get(AIAnalysis, ai["analysis_id"])).trigger == "report"

    # AI down → the report is still built and sent without the section
    monkeypatch.setattr(ai_service, "ClaudeProvider", lambda: FakeProvider(fail=AIError("down", "unavailable")))
    week = await generate_report(db_session, "weekly", date(2026, 10, 5), date(2026, 10, 11))
    assert week.data["ai_summary"] == {"status": "error", "error_kind": "unavailable"} and "Вывод ИИ" not in week.text

    monkeypatch.setattr(s, "AI_REPORTS", False)
    month = await generate_report(db_session, "monthly", date(2026, 10, 1), date(2026, 10, 31))
    assert month.data["ai_summary"] is None
    assert (await db_session.execute(select(func.count()).select_from(SalesReport))).scalar_one() == 3


# --- the Claude call through the real SDK, HTTP mocked ------------------------------------


def claude_with(handler) -> ClaudeProvider:
    client = anthropic.AsyncAnthropic(
        api_key="sk-test", base_url="http://anthropic.test", max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    return ClaudeProvider(client=client)


def message(text: str | None, stop: str = "end_turn") -> dict:
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": text}] if text is not None else [], "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 1500, "output_tokens": 700}}


@pytest.mark.asyncio
async def test_claude_request_and_parsing() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=message(answer("Менеджер-1").model_dump_json()))

    result = await claude_with(handler).complete(system="sys", prompt="<data>{}</data>", schema=PeriodAnalysis)
    assert result.output.managers[0].manager == "Менеджер-1" and (result.input_tokens, result.output_tokens) == (1500, 700)
    req = seen[0]
    body = json.loads(req.content)
    assert req.url.path == "/v1/messages" and FALLBACK_BETA in req.headers["anthropic-beta"]
    assert body["model"] == "claude-opus-5-5" and body["fallbacks"] == "default"
    assert body["output_config"]["effort"] == "medium" and body["output_config"]["format"]["type"] == "json_schema"
    assert "thinking" not in body and "temperature" not in body
    assert body["system"] == "sys" and body["messages"] == [{"role": "user", "content": "<data>{}</data>"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "payload", "kind"),
    [
        (200, message(None, stop="refusal"), "refusal"),
        (200, message('{"headline": "обрезано', stop="max_tokens"), "bad_output"),
        (401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}, "auth"),
        (429, {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}, "rate_limit"),
        (529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}, "unavailable"),
    ],
)
async def test_claude_errors(status: int, payload: dict, kind: str) -> None:
    provider = claude_with(lambda request: httpx2.Response(status, json=payload))
    with pytest.raises(AIError) as e:
        await provider.complete(system="sys", prompt="x", schema=PeriodAnalysis)
    assert e.value.kind == kind


def test_provider_needs_key(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "ANTHROPIC_API_KEY", " ")
    with pytest.raises(AIError) as e:
        ClaudeProvider()
    assert e.value.kind == "not_configured"


# --- API -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ai_api(client: AsyncClient, db_session: AsyncSession, monkeypatch) -> None:
    await _seed(db_session)
    s = get_settings()
    monkeypatch.setattr(s, "ANTHROPIC_API_KEY", "")
    headers = await _login(client, db_session, UserRole.viewer)
    st = (await client.get("/api/v1/ai/status")).json()
    assert st["configured"] is False and st["send_texts"] is False and st["used_today"] == 0
    assert "ANTHROPIC" not in json.dumps(st) and "sk-" not in json.dumps(st)
    assert (await client.post("/api/v1/ai/analyses", json={"kind": "daily"}, headers=headers)).status_code == 403

    client.cookies.clear()
    headers = await _login(client, db_session, UserRole.admin)
    assert (await client.post("/api/v1/ai/analyses", json={"kind": "daily"})).status_code == 403  # no CSRF
    r = await client.post("/api/v1/ai/analyses", json={"kind": "daily", "day": "2026-10-06"}, headers=headers)
    assert r.status_code == 409 and "ANTHROPIC_API_KEY" in r.json()["detail"]

    monkeypatch.setattr(s, "ANTHROPIC_API_KEY", "sk-test")
    fake = FakeProvider()
    monkeypatch.setattr(ai_service, "ClaudeProvider", lambda: fake)
    assert (await client.post("/api/v1/ai/analyses", json={"kind": "daily", "day": "2099-01-01"}, headers=headers)).status_code == 422
    r = await client.post("/api/v1/ai/analyses", json={"kind": "daily", "day": "2026-10-06"}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["result"]["managers"][0]["manager"] == "Иванова Мария"
    assert body["context"]["department"]["new"] == 3

    listing = (await client.get("/api/v1/ai/analyses?kind=daily")).json()["items"]
    assert [i["id"] for i in listing] == [body["id"]]
    assert (await client.get(f"/api/v1/ai/analyses/{body['id']}")).json()["headline"].startswith("Иванова Мария")
    assert (await client.get("/api/v1/ai/analyses/999")).status_code == 404

    monkeypatch.setattr(ai_service, "ClaudeProvider", lambda: FakeProvider(fail=AIError("Anthropic rate limit", "rate_limit")))
    r = await client.post("/api/v1/ai/analyses", json={"kind": "weekly", "day": "2026-10-06"}, headers=headers)
    assert r.status_code == 429

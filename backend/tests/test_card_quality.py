"""Card quality: patterns from the regulations, per-stage checks, comment sync, batch safety, API."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.card_quality import (
    TITLE_RE,
    card_quality,
    comment_has_form,
    default_checks,
    is_filled,
    resolve_field_hints,
)
from app.auth.password import hash_password
from app.integrations.bitrix.client import BitrixClient, BitrixClientError
from app.models.auth import User, UserRole
from app.models.crm import CrmDeal, CrmManager, CrmPipeline, CrmStage, DealComment, DealStageHistory
from app.repositories.sync import SyncRepository
from app.services.sync_service import COMMENTS_STATE, DEAL_FIELDS_STATE, SyncOrchestrator, comment_text

FORM = "Дата: 23.09.26\nЦель: Выявить потребность.\nИтог: Жду проект свайного поля.\nСледующий шаг: 24.09.26 связаться"
FIELDS = {
    "UF_CRM_PROFIT": {"label": "Прибыль по расчету", "type": "money"},
    "UF_CRM_MOUNT": {"label": "Ориентировочная дата монтажа", "type": "date"},
    "UF_CRM_REASON": {"label": "Причина закрытия", "type": "enumeration"},
    "UF_CRM_OTHER": {"label": "Источник", "type": "string"},
}


@pytest.mark.parametrize(
    ("title", "ok"),
    [
        ("Алексей С30.20 26шт Чехов", True),  # the regulations' example
        ("Алексей, С35.30, 40 шт, Чехов", True),
        ("Мария C30.20 12шт. Серпухов", True),  # Latin C typed by mistake
        ("Сделка #123", False),
        ("Алексей С30.20 26шт", False),  # no place
        ("Новая заявка с Авито", False),
    ],
)
def test_title_template(title: str, ok: bool) -> None:
    assert bool(TITLE_RE.search(title)) is ok


def test_comment_form_and_cleanup() -> None:
    assert comment_has_form(FORM)
    assert comment_has_form("ДАТА - 23.09 / ЦЕЛЬ — расчёт / ИТОГ: ок / СЛЕДУЮЩИЙ ШАГ: звонок")
    assert not comment_has_form("Позвонила, не ответил. Перезвоню завтра")
    assert not comment_has_form("Дата: 23.09 Цель: расчёт Итог: ок")  # next step missing
    assert comment_text("[b]Дата:[/b] 23.09<br/>Цель: расчёт&nbsp;[URL=https://x]КП[/URL]") == "Дата: 23.09 Цель: расчёт\xa0КП"


def test_is_filled() -> None:
    assert not any(is_filled(v) for v in (None, "", " ", "0", "0.00", [], {}, 0, Decimal("0.00")))
    assert all(is_filled(v) for v in ("SALE", "125000.00", ["1"], 5, "2026-11-10"))


def test_defaults_follow_the_regulations() -> None:
    hints = resolve_field_hints(FIELDS)
    assert hints == {"profit": "UF_CRM_PROFIT", "mount_date": "UF_CRM_MOUNT", "close_reason": "UF_CRM_REASON"}
    assert default_checks("Не обработан", hints) == []
    assert default_checks("Взят в работу (до первого контакта)", hints) == [
        "next_activity", "comment_form", "comment_after_stage", "field:TYPE_ID"]
    qual = default_checks("Контакт установлен / Квалификация", hints)
    assert {"title_template", "field:OPPORTUNITY", "field:UF_CRM_PROFIT", "field:UF_CRM_MOUNT"} <= set(qual)
    assert default_checks("Предзакрытие (контроль РОП)", hints) == ["comment_form", "field:UF_CRM_REASON"]
    assert default_checks("Ближайшее время", hints) == ["next_activity"]
    # Without a field dictionary the UF checks are simply not added
    assert "field:UF_CRM_PROFIT" not in default_checks("В работе / КП с расчетом", {})


NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


async def _seed(session: AsyncSession) -> dict:
    pipe = CrmPipeline(bitrix_id=1, name="Сваи", sort=0)
    session.add(pipe)
    await session.flush()
    st = {
        c: CrmStage(bitrix_id=f"C1:{c}", pipeline_id=pipe.id, name=n, sort=o, semantics="process")
        for c, n, o in [("NEW", "Не обработан", 10), ("TAKEN", "Взят в работу (до первого контакта)", 20),
                        ("QUAL", "Контакт установлен / Квалификация", 40)]
    }
    mgr = CrmManager(bitrix_id=7, name="Мария", last_name="Иванова")
    session.add_all([*st.values(), mgr])
    await session.flush()
    good_raw = {"TYPE_ID": "SALE", "OPPORTUNITY": "250000", "UF_CRM_PROFIT": "40000", "UF_CRM_MOUNT": "2026-12-01"}

    def deal(bid, stage, title, *, future=True, raw=good_raw, amount="250000"):
        return CrmDeal(bitrix_id=bid, title=title, category_id=1, stage_id=st[stage].id, assigned_by_id=mgr.id,
                       opportunity=Decimal(amount), closed=False, has_future_activity=future, raw=raw,
                       date_create=NOW - timedelta(days=5))

    session.add_all(
        [
            deal(1, "QUAL", "Алексей С30.20 26шт Чехов"),  # perfect
            deal(2, "QUAL", "Сделка 2", future=False, raw={**good_raw, "UF_CRM_PROFIT": ""}, amount="0"),
            deal(3, "TAKEN", "Заявка Авито", raw=None),  # fields not synced yet → field checks skipped
            deal(4, "NEW", "Новая"),  # no checks on «Не обработан»
            DealStageHistory(bitrix_id=1, deal_bitrix_id=1, stage_bitrix_id="C1:QUAL", category_id=1, created_time=NOW - timedelta(days=2)),
            DealStageHistory(bitrix_id=2, deal_bitrix_id=2, stage_bitrix_id="C1:QUAL", category_id=1, created_time=NOW - timedelta(days=1)),
            DealComment(bitrix_id=10, deal_bitrix_id=1, created=NOW - timedelta(days=1), text=FORM),
            # Deal 2: comment written *before* it reached the stage, and not in the form
            DealComment(bitrix_id=11, deal_bitrix_id=2, created=NOW - timedelta(days=3), text="позвонила"),
        ]
    )
    repo = SyncRepository(session)
    await repo.set_state(DEAL_FIELDS_STATE, FIELDS)
    await session.commit()
    return {"mgr": mgr}


@pytest.mark.asyncio
async def test_card_quality_evaluation(db_session: AsyncSession) -> None:
    await _seed(db_session)
    before_comments = await card_quality(db_session, now=NOW)
    assert any("Комментарии" in n for n in before_comments["notes"])
    assert all(i["code"] not in ("comment_form", "comment_after_stage")
               for item in before_comments["items"] for i in item["issues"])

    await SyncRepository(db_session).set_state(COMMENTS_STATE, {"at": NOW.isoformat()})
    await db_session.commit()
    r = await card_quality(db_session, now=NOW)
    assert (r["checked"], r["with_issues"]) == (3, 2)  # deal 4 on «Не обработан» is not checked
    by_id = {i["bitrix_id"]: {x["code"] for x in i["issues"]} for i in r["items"]}
    assert 1 not in by_id
    assert by_id[2] == {"next_activity", "comment_form", "comment_after_stage", "title_template",
                        "field:OPPORTUNITY", "field:UF_CRM_PROFIT"}
    assert by_id[3] == {"comment_form", "comment_after_stage"}  # TYPE_ID skipped: no raw yet
    assert any("полей" in n for n in r["notes"])
    labels = {b["code"]: b["label"] for b in r["by_check"]}
    assert labels["field:UF_CRM_PROFIT"] == "Не заполнено поле «Прибыль по расчету»"
    assert r["by_manager"][0]["share"] == 66.7

    only_title = await card_quality(db_session, now=NOW, check="title_template")
    assert [i["bitrix_id"] for i in only_title["items"]] == [2]


# --- Bitrix batch and comment sync ---------------------------------------------------


def test_batch_rejects_forbidden_inner_methods() -> None:
    client = BitrixClient(webhook_url="https://example.bitrix24.ru/rest/1/xxx/")
    with pytest.raises(BitrixClientError) as exc:
        import asyncio

        asyncio.run(client.call_batch({"x": ("crm.deal.update", {"id": 1, "fields": {"TITLE": "hack"}})}))
    assert exc.value.kind == "forbidden_method"


@pytest.mark.asyncio
async def test_timeline_comments_batch_request_and_parsing(monkeypatch) -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        cmd = body["cmd"]
        result = {}
        for key, q in cmd.items():
            method, _, query = q.partition("?")
            assert method == "crm.timeline.comment.list"
            parsed = parse_qs(query)
            deal = parsed["filter[ENTITY_ID]"][0]
            assert parsed["filter[ENTITY_TYPE]"] == ["deal"] and parsed["order[ID]"] == ["DESC"]
            result[key] = [{"ID": f"{deal}00", "CREATED": "2026-11-09T10:00:00+03:00", "COMMENT": FORM, "AUTHOR_ID": "7"}]
        return httpx.Response(200, json={"result": {"result": result, "result_error": {}}})

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: original(*a, **{**kw, "transport": transport}))
    client = BitrixClient(webhook_url="https://example.bitrix24.ru/rest/1/xxx/", rate_limit_rps=1000)
    out = await client.crm_timeline_comments(list(range(1, 61)))  # 60 deals → 2 batch requests
    assert len(seen) == 2 and len(seen[0]["cmd"]) == 50 and len(seen[1]["cmd"]) == 10
    assert out[5][0]["ID"] == "500"


@pytest.mark.asyncio
async def test_run_comments_upserts_and_tracks_edits(db_session: AsyncSession) -> None:
    await _seed(db_session)
    fake = AsyncMock()
    fake.crm_timeline_comments.return_value = {
        1: [{"ID": "10", "CREATED": "2026-11-09T10:00:00+03:00", "COMMENT": "[b]Дата:[/b] edited", "AUTHOR_ID": "7"},
            {"ID": "77", "CREATED": "2026-11-10T10:00:00+03:00", "COMMENT": "новый", "AUTHOR_ID": "x"}],
    }
    orch = SyncOrchestrator(db_session, client=fake)
    orch._sync_repo.try_advisory_lock = AsyncMock(return_value=True)  # type: ignore[method-assign]
    orch._sync_repo.advisory_unlock = AsyncMock()  # type: ignore[method-assign]
    await orch.run_comments()

    asked = set(fake.crm_timeline_comments.call_args.args[0])
    assert asked == {1, 2, 3, 4}  # every open deal of the synced pipelines
    rows = {c.bitrix_id: c for c in (await db_session.execute(select(DealComment))).scalars()}
    assert rows[10].text == "Дата: edited" and rows[77].author_id is None
    assert await SyncRepository(db_session).get_state(COMMENTS_STATE) is not None


# --- API -----------------------------------------------------------------------------


async def _login(client: AsyncClient, session: AsyncSession, role: UserRole) -> dict:
    email = f"{role.value}-q@ex.com"
    session.add(User(email=email, password_hash=hash_password("password123"), role=role, is_active=True))
    await session.commit()
    await client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return {"X-CSRF-Token": client.cookies.get("focus_csrf") or ""}


@pytest.mark.asyncio
async def test_quality_rules_api(client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed(db_session)
    headers = await _login(client, db_session, UserRole.viewer)
    data = (await client.get("/api/v1/quality/rules")).json()
    assert {"code": "UF_CRM_PROFIT", "label": "Прибыль по расчету"} in data["fields"]
    assert (await client.get("/api/v1/quality")).status_code == 200
    body = {"checks": ["next_activity", "field:UF_CRM_OTHER"]}
    assert (await client.put("/api/v1/quality/rules/C1:QUAL", json=body, headers=headers)).status_code == 403

    client.cookies.clear()
    headers = await _login(client, db_session, UserRole.admin)
    bad = await client.put("/api/v1/quality/rules/C1:QUAL", json={"checks": ["field:UF_NOPE"]}, headers=headers)
    assert bad.status_code == 422
    ok = await client.put("/api/v1/quality/rules/C1:QUAL", json=body, headers=headers)
    assert ok.json()["source"] == "custom" and ok.json()["check_labels"]["field:UF_CRM_OTHER"] == "Не заполнено поле «Источник»"
    reset = await client.delete("/api/v1/quality/rules/C1:QUAL", headers=headers)
    assert reset.json()["source"] == "default" and "title_template" in reset.json()["checks"]

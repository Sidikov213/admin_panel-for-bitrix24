"""Avito dialogs: new requests, first reply speed (working time), unanswered, items, Bitrix link."""

from __future__ import annotations

import statistics
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.kpi import _as_utc
from app.core.config import get_settings
from app.core.timezone import local_day_bounds, utc_now
from app.core.work_calendar import get_work_calendar
from app.integrations.bitrix.links import deal_url
from app.models.avito import AvitoChat
from app.models.crm import CrmDeal, CrmStage

CHAT_URL = "https://www.avito.ru/profile/messenger/channel/{chat_id}"


def chat_url(chat_id: str) -> str:
    return CHAT_URL.format(chat_id=chat_id)


def account_names() -> dict[int, str]:
    return {a["id"]: a["name"] for a in get_settings().avito_accounts}


async def _deal_outcomes(session: AsyncSession, bids: set[int]) -> dict[int, dict[str, Any]]:
    if not bids:
        return {}
    rows = (
        await session.execute(
            select(CrmDeal.id, CrmDeal.bitrix_id, CrmDeal.title, CrmDeal.closed, CrmStage.semantics, CrmStage.name)
            .outerjoin(CrmStage, CrmStage.id == CrmDeal.stage_id)
            .where(CrmDeal.bitrix_id.in_(list(bids)))
        )
    ).all()
    return {
        bid: {"deal_id": did, "title": title, "stage": stage_name,
              "won": bool(closed and sem == "success"), "lost": bool(closed and sem == "failure")}
        for did, bid, title, closed, sem, stage_name in rows
    }


def _chat_row(c: AvitoChat, *, reply: float | None, waiting: float | None, late: bool,
              deal: dict[str, Any] | None, names: dict[int, str]) -> dict[str, Any]:
    return {
        "chat_id": c.chat_id,
        "account_id": c.account_id,
        "account": names.get(c.account_id, str(c.account_id)),
        "client_name": c.client_name,
        "item_id": c.item_id,
        "item_title": c.item_title,
        "item_url": c.item_url,
        "first_in_at": _as_utc(c.first_in_at).isoformat() if c.first_in_at else None,
        "first_reply_at": _as_utc(c.first_reply_at).isoformat() if c.first_reply_at else None,
        "last_message_at": _as_utc(c.last_message_at).isoformat() if c.last_message_at else None,
        "last_direction": c.last_direction,
        "messages_count": c.messages_count,
        "reply_seconds": round(reply) if reply is not None else None,
        "waiting_seconds": round(waiting) if waiting is not None else None,
        "late": late,
        "chat_url": chat_url(c.chat_id),
        "deal": (
            {**deal, "bitrix_id": c.deal_bitrix_id, "bitrix_url": deal_url(c.deal_bitrix_id)} if deal and c.deal_bitrix_id else None
        ),
    }


async def avito_summary(
    session: AsyncSession,
    *,
    period_start: date,
    period_end: date,
    account_id: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or utc_now()
    cal = get_work_calendar()
    norm = get_settings().AVITO_REPLY_NORM_MINUTES * 60
    names = account_names()
    start_utc, _ = local_day_bounds(period_start)
    _, end_utc = local_day_bounds(period_end)

    q = select(AvitoChat)
    if account_id is not None:
        q = q.where(AvitoChat.account_id == account_id)
    chats = (await session.execute(q)).scalars().all()
    deals = await _deal_outcomes(session, {c.deal_bitrix_id for c in chats if c.deal_bitrix_id})

    new_rows: list[dict[str, Any]] = []
    unanswered: list[dict[str, Any]] = []
    for c in chats:
        first_in = _as_utc(c.first_in_at)
        reply = cal.work_seconds(first_in, _as_utc(c.first_reply_at)) if first_in and c.first_reply_at else None
        waiting_now = c.last_direction == "in"
        wait = cal.work_seconds(_as_utc(c.last_message_at), now) if waiting_now and c.last_message_at else None
        first_wait = cal.work_seconds(first_in, now) if first_in and reply is None else None
        deal = deals.get(c.deal_bitrix_id) if c.deal_bitrix_id else None
        if first_in and start_utc <= first_in <= end_utc:
            late = (reply if reply is not None else first_wait or 0) > norm
            new_rows.append(_chat_row(c, reply=reply, waiting=first_wait, late=late, deal=deal, names=names))
        # Only dialogs where the client wrote during the period: a «спасибо» from last spring is noise
        last = _as_utc(c.last_message_at)
        if waiting_now and last and last >= start_utc:
            unanswered.append(_chat_row(c, reply=reply, waiting=wait, late=(wait or 0) > norm, deal=deal, names=names))

    def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        replies = [r["reply_seconds"] for r in rows if r["reply_seconds"] is not None]
        linked = [r for r in rows if r["deal"]]
        return {
            "new": len(rows),
            "replied": len(replies),
            "reply_median_seconds": round(statistics.median(replies)) if replies else None,
            "reply_avg_seconds": round(statistics.fmean(replies)) if replies else None,
            "late": sum(r["late"] for r in rows),
            "late_share": round(sum(r["late"] for r in rows) / len(rows) * 100, 1) if rows else None,
            "no_reply": sum(r["reply_seconds"] is None for r in rows),
            "linked": len(linked),
            "linked_share": round(len(linked) / len(rows) * 100, 1) if rows else None,
            "won": sum(1 for r in linked if r["deal"]["won"]),
            "lost": sum(1 for r in linked if r["deal"]["lost"]),
        }

    by_account = []
    for acc in sorted({r["account_id"] for r in new_rows} | set(names if account_id is None else [account_id])):
        rows = [r for r in new_rows if r["account_id"] == acc]
        by_account.append({"account_id": acc, "name": names.get(acc, str(acc)), **summarize(rows),
                           "unanswered_now": sum(1 for u in unanswered if u["account_id"] == acc)})

    items: dict[Any, dict[str, Any]] = {}
    for r in new_rows:
        key = r["item_id"] or r["item_title"] or "—"
        it = items.setdefault(key, {"item_id": r["item_id"], "title": r["item_title"] or "Без объявления",
                                    "url": r["item_url"], "account": r["account"], "rows": []})
        it["rows"].append(r)
    by_item = sorted(
        ({k: v for k, v in it.items() if k != "rows"} | summarize(it["rows"]) for it in items.values()),
        key=lambda x: -x["new"],
    )

    unanswered.sort(key=lambda r: -(r["waiting_seconds"] or 0))
    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "norm_seconds": norm,
        "summary": {**summarize(new_rows), "unanswered_now": len(unanswered),
                    "unanswered_late": sum(u["late"] for u in unanswered)},
        "by_account": by_account,
        "by_item": by_item[:30],
        "unanswered": unanswered[:50],
        "slowest": sorted(new_rows, key=lambda r: -(r["reply_seconds"] if r["reply_seconds"] is not None else r["waiting_seconds"] or 0))[:20],
        "definitions": {
            "new": "Диалоги, в которых первое сообщение клиента пришло в периоде.",
            "reply": "Рабочее время от первого сообщения клиента до первого ответа с нашей стороны.",
            "unanswered": "Последнее сообщение — от клиента (написал в выбранном периоде), ответа ещё нет.",
            "linked": "Диалог связан со сделкой Bitrix: ссылка на чат найдена в полях или комментариях сделки.",
        },
        "computed_at": now.isoformat(),
    }

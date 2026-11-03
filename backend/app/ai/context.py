"""The model's input: numbers already computed by the panel, without names, clients or links.

Texts (comments, Avito dialogues) are added only with AI_SEND_TEXTS=true, cleaned by `scrub`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.privacy import account_alias, manager_alias, scrub
from app.analytics.avito import avito_summary
from app.core.config import get_settings
from app.core.timezone import local_day_bounds
from app.models.avito import AvitoChat, AvitoMessage
from app.models.crm import CrmDeal, CrmStage, DealComment

COMMENTS_PER_MANAGER = 8
COMMENTS_TOTAL = 80
AVITO_DIALOGS = 20
AVITO_MESSAGES_PER_DIALOG = 6


def _minutes(seconds: float | None) -> int | None:
    return round(seconds / 60) if seconds is not None else None


def _metrics(m: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in m.items() if not k.endswith("_seconds")}
    if "reaction_median_seconds" in m:
        out["reaction_median_work_minutes"] = _minutes(m["reaction_median_seconds"])
    return out


def numbers_context(report: dict[str, Any], avito: dict[str, Any] | None) -> dict[str, Any]:
    s = get_settings()
    plan = report.get("plan")
    ctx: dict[str, Any] = {
        "period": {"kind": report["kind"], "start": report["period_start"], "end": report["period_end"]},
        "rules": {
            "work_schedule": f"{s.WORK_DAYS} {s.WORK_HOURS}, общий отпуск {s.COMPANY_HOLIDAYS}",
            "reaction_and_reply_minutes": "рабочие минуты",
            "avito_first_reply_norm_work_minutes": s.AVITO_REPLY_NORM_MINUTES,
            "next_activity_required": True,
            "comment_form": "Дата / Цель / Итог / Следующий шаг",
        },
        "department": _metrics(report["metrics"]),
        "previous_period": _metrics(report["previous"]),
        "plan": (
            {k: plan[k] for k in ("currency", "plan", "fact", "percent", "expected", "forecast", "forecast_reliable",
                                  "remaining", "days_total", "days_elapsed", "days_left", "per_day_needed", "status")}
            if plan
            else None
        ),
        "managers": [
            {"manager": manager_alias(r["manager_id"]),
             **{k: r[k] for k in ("new", "won", "lost", "active", "overdue", "overdue_open", "overdue_deals", "stuck",
                                  "stuck_share", "overdue_share", "plan_percent")},
             "reaction_median_work_minutes": _minutes(r["reaction_median_seconds"])}
            for r in report["managers"]
        ],
        "problem_stages": report.get("problem_stages", []),
        "card_quality": {
            "checked": report["card_quality"]["checked"],
            "with_issues": report["card_quality"]["with_issues"],
            "share": report["card_quality"]["share"],
            "by_check": [{"check": b["label"], "count": b["count"]} for b in report["card_quality"]["by_check"]],
            "no_next_activity": report["card_quality"]["no_next_activity"],
        },
        "data_warning": report.get("data_warning"),
    }
    if avito and (avito["summary"]["new"] or avito["summary"]["unanswered_now"]):
        keys = ("new", "replied", "late", "late_share", "no_reply", "linked_share", "won", "lost")
        ctx["avito"] = {
            "summary": {**{k: avito["summary"][k] for k in keys},
                        "reply_median_work_minutes": _minutes(avito["summary"]["reply_median_seconds"]),
                        "unanswered_now": avito["summary"]["unanswered_now"]},
            "by_account": [
                {"account": account_alias(a["account_id"]), **{k: a[k] for k in keys},
                 "reply_median_work_minutes": _minutes(a["reply_median_seconds"]), "unanswered_now": a["unanswered_now"]}
                for a in avito["by_account"]
                if a["new"] or a["unanswered_now"]
            ],
        }
    return ctx


async def comments_sample(session: AsyncSession, start: date, end: date) -> list[dict[str, Any]]:
    start_utc, _ = local_day_bounds(start)
    _, end_utc = local_day_bounds(end)
    rows = (
        await session.execute(
            select(DealComment.text, DealComment.created, CrmDeal.bitrix_id, CrmDeal.assigned_by_id, CrmStage.name)
            .join(CrmDeal, CrmDeal.bitrix_id == DealComment.deal_bitrix_id)
            .outerjoin(CrmStage, CrmStage.id == CrmDeal.stage_id)
            .where(DealComment.created >= start_utc, DealComment.created <= end_utc)
            .order_by(DealComment.created.desc())
        )
    ).all()
    per: dict[int | None, int] = {}
    out = []
    for text, _created, bid, mid, stage in rows:
        if len(out) >= COMMENTS_TOTAL or per.get(mid, 0) >= COMMENTS_PER_MANAGER or not text.strip():
            continue
        per[mid] = per.get(mid, 0) + 1
        out.append({"manager": manager_alias(mid) if mid else "без менеджера", "deal": f"№{bid}", "stage": stage,
                    "text": scrub(text)})
    return out


async def avito_sample(session: AsyncSession, start: date, end: date) -> list[dict[str, Any]]:
    start_utc, _ = local_day_bounds(start)
    _, end_utc = local_day_bounds(end)
    chats = (
        await session.execute(
            select(AvitoChat)
            .where(AvitoChat.first_in_at >= start_utc, AvitoChat.first_in_at <= end_utc)
            .order_by(AvitoChat.first_in_at.desc())
            .limit(AVITO_DIALOGS)
        )
    ).scalars().all()
    out = []
    for c in chats:
        msgs = (
            await session.execute(
                select(AvitoMessage)
                .where(AvitoMessage.chat_id == c.chat_id, AvitoMessage.is_system.is_(False))
                .order_by(AvitoMessage.created)
                .limit(AVITO_MESSAGES_PER_DIALOG)
            )
        ).scalars().all()
        lines = [f"{'Клиент' if m.direction == 'in' else 'Мы'}: {scrub(m.text, 300)}" for m in msgs if m.text.strip()]
        if lines:
            # Chat ids are opaque Avito ids, not client data
            out.append({"account": account_alias(c.account_id), "chat": c.chat_id[-8:], "item": c.item_title,
                        "dialog": lines})
    return out


async def build_context(
    session: AsyncSession, report: dict[str, Any], history: list[dict[str, Any]]
) -> dict[str, Any]:
    s = get_settings()
    start, end = date.fromisoformat(report["period_start"]), date.fromisoformat(report["period_end"])
    has_avito = (await session.execute(select(AvitoChat.id).limit(1))).first() is not None
    avito = await avito_summary(session, period_start=start, period_end=end) if has_avito else None
    ctx = numbers_context(report, avito)
    if history:
        ctx["previous_ai_findings"] = history
    if s.AI_SALES_SCRIPT.strip():
        ctx["sales_script"] = s.AI_SALES_SCRIPT.strip()[:6000]
    if s.AI_SEND_TEXTS:
        ctx["texts"] = {"comments": await comments_sample(session, start, end),
                        "avito_dialogs": await avito_sample(session, start, end)}
    return ctx

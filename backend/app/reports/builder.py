"""Collect report numbers from the existing analytics and render them for Telegram.

Every number here comes from the same functions the panel pages use, so a report never
disagrees with the dashboard, «Зависшие сделки», «Просроченные дела» or «Скорость реакции».
"""

from __future__ import annotations

import calendar as pycal
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.card_quality import card_quality
from app.analytics.kpi import compute_period_kpis, overdue_activities_query
from app.analytics.overdue import overdue_report
from app.analytics.plan import targets_progress
from app.analytics.sla import reaction_stats, stuck_deals
from app.core.config import get_settings
from app.core.timezone import local_day_bounds, utc_now
from app.core.work_calendar import WorkCalendar, get_work_calendar
from app.integrations.bitrix.links import deal_url
from app.models.crm import CrmActivity, CrmDeal, CrmManager, CrmStage
from app.notifications.digest import _data_warning, _e, _plan_line, format_money

KINDS = ("daily", "weekly", "monthly")
MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь",
          "ноябрь", "декабрь"]


# --- periods -------------------------------------------------------------------------


def period_for(kind: str, ref: date) -> tuple[date, date]:
    """The day, the Mon–Sun week or the calendar month containing `ref`."""
    if kind == "daily":
        return ref, ref
    if kind == "weekly":
        start = ref - timedelta(days=ref.weekday())
        return start, start + timedelta(days=6)
    if kind == "monthly":
        return ref.replace(day=1), ref.replace(day=pycal.monthrange(ref.year, ref.month)[1])
    raise ValueError(f"unknown report kind: {kind}")


def previous_period(kind: str, start: date, end: date, cal: WorkCalendar) -> tuple[date, date]:
    if kind == "daily":
        d = start - timedelta(days=1)
        # Compare Monday with Friday, not with Sunday
        for _ in range(40):
            if cal.is_workday(d):
                break
            d -= timedelta(days=1)
        return d, d
    if kind == "weekly":
        return start - timedelta(days=7), end - timedelta(days=7)
    prev_last = start - timedelta(days=1)
    return prev_last.replace(day=1), prev_last


def period_title(kind: str, start: date, end: date) -> str:
    if kind == "daily":
        return f"Итоги дня · {start:%d.%m.%Y}"
    if kind == "weekly":
        return f"Итоги недели · {start:%d.%m}–{end:%d.%m.%Y}"
    return f"Итоги месяца · {MONTHS[start.month - 1]} {start.year}"


# --- numbers -------------------------------------------------------------------------


async def _per_manager_outcomes(session: AsyncSession, start: date, end: date) -> dict[int, dict[str, int]]:
    start_utc, _ = local_day_bounds(start)
    _, end_utc = local_day_bounds(end)
    out: dict[int, dict[str, int]] = {}

    def bucket(mid: int) -> dict[str, int]:
        return out.setdefault(mid, _empty_row())

    created = await session.execute(
        select(CrmDeal.assigned_by_id, func.count())
        .where(CrmDeal.missing_from_bitrix.is_(False), CrmDeal.date_create >= start_utc, CrmDeal.date_create <= end_utc)
        .group_by(CrmDeal.assigned_by_id)
    )
    for mid, n in created.all():
        if mid:
            bucket(mid)["new"] = n
    closed_at = func.coalesce(CrmDeal.closedate, CrmDeal.date_modify)
    closed = await session.execute(
        select(CrmDeal.assigned_by_id, CrmStage.semantics, func.count())
        .join(CrmStage, CrmStage.id == CrmDeal.stage_id)
        .where(
            CrmDeal.missing_from_bitrix.is_(False),
            CrmDeal.closed.is_(True),
            CrmStage.semantics.in_(("success", "failure")),
            closed_at >= start_utc,
            closed_at <= end_utc,
        )
        .group_by(CrmDeal.assigned_by_id, CrmStage.semantics)
    )
    for mid, sem, n in closed.all():
        if mid:
            bucket(mid)["won" if sem == "success" else "lost"] = n
    active = await session.execute(
        select(CrmDeal.assigned_by_id, func.count())
        .where(CrmDeal.missing_from_bitrix.is_(False), CrmDeal.closed.is_(False))
        .group_by(CrmDeal.assigned_by_id)
    )
    for mid, n in active.all():
        if mid:
            bucket(mid)["active"] = n
    open_overdue = await session.execute(
        overdue_activities_query(utc_now(), CrmDeal.assigned_by_id, func.count(func.distinct(CrmActivity.bitrix_id)))
        .group_by(CrmDeal.assigned_by_id)
    )
    for mid, n in open_overdue.all():
        if mid:
            bucket(mid)["overdue_open"] = n
    # For the share: active deals that have at least one open overdue activity.
    # Counting activities instead gives "140 %" (several per deal, also on closed deals).
    overdue_deals = await session.execute(
        overdue_activities_query(utc_now(), CrmDeal.assigned_by_id, func.count(func.distinct(CrmDeal.id)))
        .where(CrmDeal.closed.is_(False))
        .group_by(CrmDeal.assigned_by_id)
    )
    for mid, n in overdue_deals.all():
        if mid:
            bucket(mid)["overdue_deals"] = n
    return out


def _empty_row() -> dict[str, int]:
    return {"new": 0, "won": 0, "lost": 0, "active": 0, "overdue": 0, "overdue_open": 0, "overdue_deals": 0}


async def build_report(session: AsyncSession, kind: str, start: date, end: date) -> dict[str, Any]:
    settings = get_settings()
    cal = get_work_calendar()
    top_n = settings.REPORT_TOP_N
    prev_start, prev_end = previous_period(kind, start, end, cal)

    kpis = await compute_period_kpis(session, start, end, include_series=False)
    prev_kpis = await compute_period_kpis(session, prev_start, prev_end, include_series=False)
    overdue = await overdue_report(session, date_from=start, date_to=end, limit=10000)
    prev_overdue = await overdue_report(session, date_from=prev_start, date_to=prev_end, limit=1)
    stuck = await stuck_deals(session)
    reaction = await reaction_stats(session, period_start=start, period_end=end)
    prev_reaction = await reaction_stats(session, period_start=prev_start, period_end=prev_end)

    plans = sorted(await targets_progress(session, end), key=lambda p: p.days_total)
    plan = next((p for p in plans if p.manager_id is None), None)
    manager_plans = {p.manager_id: p for p in reversed(plans) if p.manager_id is not None}

    per = await _per_manager_outcomes(session, start, end)
    for item in overdue["items"]:
        if item["manager_id"]:
            per.setdefault(item["manager_id"], _empty_row())
            per[item["manager_id"]]["overdue"] += 1
    stuck_by_m = {m["manager_id"]: m for m in stuck["by_manager"]}
    react_by_m = {m["manager_id"]: m for m in reaction["managers"]}
    names = {
        m.id: f"{m.last_name} {m.name}".strip()
        for m in (await session.execute(select(CrmManager).where(CrmManager.id.in_(list(per) or [0])))).scalars()
    }
    managers = []
    for mid, v in per.items():
        sm = stuck_by_m.get(mid, {})
        rm = react_by_m.get(mid)
        row = {
            "manager_id": mid,
            "name": names.get(mid, f"#{mid}"),
            **v,
            "stuck": sm.get("stuck", 0),
            "stuck_share": sm.get("share"),
            "overdue_share": round(v["overdue_deals"] / v["active"] * 100, 1) if v["active"] else None,
            "reaction_median_seconds": rm["contact"]["median_seconds"] if rm else None,
            "plan_percent": manager_plans[mid].percent if mid in manager_plans else None,
        }
        # Managers with nothing going on (fired, other departments) are noise in a report
        if any(row[k] for k in ("new", "won", "lost", "active", "overdue", "overdue_open")):
            managers.append(row)
    managers.sort(key=lambda m: (-(m["overdue_open"] + m["stuck"]), m["name"]))

    no_next = (
        await session.execute(
            select(CrmDeal)
            .where(CrmDeal.closed.is_(False), CrmDeal.missing_from_bitrix.is_(False), CrmDeal.has_future_activity.is_(False))
            .order_by(CrmDeal.opportunity.desc().nullslast(), CrmDeal.id)
        )
    ).scalars().all()
    quality = await card_quality(session)
    stage_overdue: dict[str, int] = {}
    for item in overdue["items"]:
        if item["stage"]:
            stage_overdue[item["stage"]] = stage_overdue.get(item["stage"], 0) + 1
    problem_stages = sorted(
        (
            {"name": s["name"], "pipeline": s["pipeline"], "rule": s["rule"], "open": s["open"], "stuck": s["stuck"],
             "overdue": stage_overdue.get(s["name"], 0)}
            for s in stuck["by_stage"]
            if s["stuck"] or stage_overdue.get(s["name"])
        ),
        key=lambda s: -(s["stuck"] + s["overdue"]),
    )

    def metrics(k: dict, od: dict, rc: dict) -> dict[str, Any]:
        return {
            "new": k["new_deals_count"],
            "won": k["won_count"],
            "won_sum": k["sum_won_opportunity"],
            "lost": k["lost_count"],
            "overdue": od["summary"]["total"],
            "reaction_median_seconds": rc["summary"]["contact"]["median_seconds"],
            "reaction_late_share": rc["summary"]["late_share"],
        }

    return {
        "kind": kind,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "title": period_title(kind, start, end),
        "previous": {"period_start": prev_start.isoformat(), "period_end": prev_end.isoformat(),
                     **metrics(prev_kpis, prev_overdue, prev_reaction)},
        "metrics": {
            **metrics(kpis, overdue, reaction),
            "overdue_open_now": kpis["open_overdue"],
            "overdue_closed_late": overdue["summary"]["closed_late"],
            "stuck_now": stuck["stuck_total"],
            "open_now": stuck["open_total"],
            "no_next_activity_now": len(no_next),
        },
        "plan": plan.to_dict() if plan else None,
        "managers": managers,
        "problem_deals": [
            {k: d[k] for k in ("deal_id", "bitrix_id", "title", "manager", "stage", "rule", "in_stage_seconds", "unit",
                                "bitrix_url")}
            for d in stuck["items"][:top_n]
        ],
        "card_quality": {
            "no_next_activity": len(no_next),
            "checked": quality["checked"],
            "with_issues": quality["with_issues"],
            "share": quality["share"],
            "by_check": quality["by_check"][:top_n],
            "deals": [
                {"deal_id": d.id, "bitrix_id": d.bitrix_id, "title": d.title,
                 "opportunity": float(d.opportunity) if d.opportunity is not None else None,
                 "bitrix_url": deal_url(d.bitrix_id)}
                for d in no_next[:top_n]
            ],
        },
        # A single day is too short for stage patterns (ТЗ §12: «проблемные этапы» are a trend)
        "problem_stages": problem_stages[:top_n] if kind != "daily" else [],
        "data_warning": await _data_warning(session),
        "ai_summary": None,
        "generated_at": utc_now().isoformat(),
    }


# --- rendering (Telegram HTML) -------------------------------------------------------


def fmt_duration(seconds: float | None, *, work: bool = False) -> str:
    if seconds is None:
        return "—"
    s = int(round(seconds))
    if work:
        h, m = s // 3600, (s % 3600) // 60
        return (f"{h} ч {m} мин" if h and m else f"{h} ч" if h else f"{m} мин") + " раб."
    d, h, m = s // 86400, (s % 86400) // 3600, (s % 3600) // 60
    if d:
        return f"{d} дн." + (f" {h} ч" if h else "")
    return f"{h} ч {m} мин" if h else f"{m} мин"


# How many rows of each list fit a phone screen without scrolling past the point
LIST_ROWS = 5
PERIOD_WORD = {"daily": "За день", "weekly": "За неделю", "monthly": "За месяц"}


def _was(value: Any, fmt=str) -> str:
    return f" (было {fmt(value)})" if value is not None else ""


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _link(title: str, url: str | None, limit: int = 48) -> str:
    t = _e(_short(title, limit))
    return f'<a href="{_e(url)}">{t}</a>' if url else t


def _stay(seconds: float | None, *, work: bool) -> str:
    """Time on a stage, rounded: nobody needs the minutes of a deal stuck for 288 hours."""
    if seconds is None:
        return "—"
    s = int(round(seconds))
    if not work:
        d = s // 86400
        return f"{d} дн." if d else fmt_duration(s)
    h, m = s // 3600, (s % 3600) // 60
    if h >= 10:
        return f"{h} ч"
    return f"{h} ч {m} мин" if h and m else f"{h} ч" if h else f"{m} мин"


def _nonzero(pairs: list[tuple[str, int]]) -> list[str]:
    return [f"{label} {value}" for label, value in pairs if value]


def render_report(data: dict[str, Any]) -> str:
    m, p = data["metrics"], data["previous"]
    pct = lambda v: f"{v:g}".replace(".", ",") + "%"  # noqa: E731
    react = lambda sec: fmt_duration(sec, work=True).removesuffix(" раб.")  # noqa: E731
    period = PERIOD_WORD.get(data["kind"], "За период")
    lines = [f"📊 <b>{_e(data['title'])}</b>"]
    if data.get("data_warning"):
        lines.append(f"⚠️ <i>{_e(data['data_warning'])}</i>")

    lines += [
        "",
        "💰 <b>Продажи</b>",
        f"Выиграно: <b>{m['won']}</b>" + (f" на <b>{format_money(m['won_sum'])}</b>" if m["won"] else "") + _was(p["won"]),
        f"Новых сделок: <b>{m['new']}</b>{_was(p['new'])}",
        f"Проиграно: <b>{m['lost']}</b>{_was(p['lost'])}",
    ]
    if data.get("plan"):
        from app.analytics.plan import TargetProgress

        plan = data["plan"]
        tp = TargetProgress(**{**plan, "period_start": date.fromisoformat(plan["period_start"]),
                               "period_end": date.fromisoformat(plan["period_end"])})
        lines.append(_plan_line(tp))

    lines += [
        "",
        "⏱ <b>Дисциплина</b>",
        f"Новых просрочек: <b>{m['overdue']}</b>{_was(p['overdue'])}",
        f"Всего не закрыто просрочек: <b>{m['overdue_open_now']}</b>",
        f"Зависло сделок: <b>{m['stuck_now']}</b> из {m['open_now']}",
        f"До первого контакта: <b>{react(m['reaction_median_seconds'])}</b>"
        + (_was(react(p["reaction_median_seconds"])) if p["reaction_median_seconds"] is not None else ""),
    ]

    if data["managers"]:
        lines += ["", "👥 <b>Менеджеры</b>"]
        quiet: list[str] = []
        for r in data["managers"]:
            done = _nonzero([("новых", r["new"]), ("выиграно", r["won"]), ("проиграно", r["lost"]),
                             ("просрочек", r["overdue"])])
            if r["reaction_median_seconds"] is not None:
                done.append(f"контакт через {react(r['reaction_median_seconds'])}")
            if r["plan_percent"] is not None:
                done.append(f"план {pct(r['plan_percent'])}")
            debt = _nonzero([("не закрыто просрочек", r["overdue_open"]), ("зависло сделок", r["stuck"])])
            if not done and not debt:
                quiet.append(_e(r["name"]))
                continue
            lines += ["", f"<b>{_e(r['name'])}</b>"]
            if done:
                lines.append(f"{period}: " + " · ".join(done))
            if debt:
                lines.append("Сейчас: " + " · ".join(debt))
        if quiet:
            lines += ["", "<i>Без событий и долгов: " + ", ".join(quiet) + "</i>"]

    if data["problem_deals"]:
        lines += ["", "🔥 <b>Требуют внимания</b>"]
        for i, d in enumerate(data["problem_deals"][:LIST_ROWS], 1):
            stay = _stay(d["in_stage_seconds"], work=d["unit"] != "calendar_days")
            lines += [
                "",
                f"{i}. {_link(f'№{d['bitrix_id']} {d['title']}', d['bitrix_url'])}",
                f"«{_e(_short(d['stage'], 40))}» — уже <b>{stay}</b> при сроке {_e(d['rule'])}"
                + (f" · {_e(d['manager'])}" if d["manager"] else ""),
            ]

    cq = data["card_quality"]
    if cq.get("with_issues"):
        lines += [
            "",
            "📝 <b>Качество карточек</b>",
            f"С нарушениями: <b>{cq['with_issues']}</b> из {cq['checked']} ({pct(cq['share'] or 0)})",
        ]
        for b in cq.get("by_check", [])[:LIST_ROWS]:
            lines.append(f"• {b['count']} — {_e(_short(b['label'], 62))}")

    if cq["no_next_activity"]:
        lines += ["", f"📌 <b>Без следующего дела: {cq['no_next_activity']}</b>"]
        if cq["deals"]:
            lines.append("Самые крупные:")
        for d in cq["deals"][:LIST_ROWS]:
            lines.append(f"• {_link(f'№{d['bitrix_id']} {d['title']}', d['bitrix_url'], 40)}"
                         + (f" — {format_money(d['opportunity'])}" if d["opportunity"] else ""))

    if data["kind"] != "daily" and data["problem_stages"]:
        lines += ["", "🚧 <b>Проблемные этапы</b>"]
        for s in data["problem_stages"][:LIST_ROWS]:
            lines.append(f"• {_e(s['name'])} — зависло {s['stuck']} из {s['open']} · просрочек {s['overdue']}")

    ai = data.get("ai_summary")
    if ai and ai.get("status") == "ok" and ai.get("headline"):
        lines += ["", "🤖 <b>Вывод ИИ</b>", _e(ai["headline"])]
        lines += [f"• {_e(p)}" for p in ai.get("points", [])]
        if ai.get("recommendations"):
            lines.append("<i>Что сделать:</i>")
            lines += [f"{i}. {_e(r)}" for i, r in enumerate(ai["recommendations"], 1)]

    lines += ["", "<i>Часы считаются рабочие. Подробности — в панели.</i>"]
    return "\n".join(lines)


def report_period_for_schedule(kind: str, today: date) -> tuple[date, date]:
    """Scheduled runs: today's report at the end of the day, last week's on Monday."""
    if kind == "weekly":
        return period_for("weekly", today - timedelta(days=7))
    if kind == "monthly":
        return period_for("monthly", today.replace(day=1) - timedelta(days=1))
    return period_for("daily", today)


def local_today(now: datetime | None = None) -> date:
    from app.core.timezone import app_tz

    return (now or utc_now()).astimezone(app_tz()).date()

"""Build the daily sales digest from local data and render it as Telegram HTML."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analytics.kpi import _as_utc, compute_period_kpis, overdue_activities_query
from app.core.config import get_settings
from app.core.timezone import app_tz, utc_now
from app.models.crm import CrmActivity, CrmDeal, CrmManager
from app.repositories.sync import SyncRepository

# Sync older than this is called out in the digest instead of silently reporting stale numbers
STALE_SYNC_AFTER = timedelta(hours=3)


@dataclass
class DigestDeal:
    deal_id: int
    bitrix_id: int
    title: str
    opportunity: Decimal | None
    manager: str | None
    url: str | None
    overdue_count: int = 0
    idle_days: int | None = None


@dataclass
class ManagerDigest:
    manager_id: int
    name: str
    telegram_chat_id: str | None
    overdue_activities: int = 0
    no_future: list[DigestDeal] = field(default_factory=list)
    idle: list[DigestDeal] = field(default_factory=list)
    overdue_deals: list[DigestDeal] = field(default_factory=list)

    @property
    def has_problems(self) -> bool:
        return bool(self.overdue_activities or self.no_future or self.idle)


@dataclass
class Digest:
    day: date
    new_yesterday: int
    won_yesterday: int
    won_sum_yesterday: float
    active_deals: int
    overdue_activities: int
    no_future_count: int
    idle_count: int
    stale_days: int
    top_n: int
    # Managers with problems, worst first (team summary)
    managers: list[ManagerDigest]
    # Every manager, including those with nothing to report (personal messages)
    managers_all: list[ManagerDigest]
    top_idle: list[DigestDeal]
    data_warning: str | None


def _manager_name(m: CrmManager | None) -> str | None:
    if m is None:
        return None
    return f"{m.last_name} {m.name}".strip() or None


def _deal_url(bitrix_id: int) -> str | None:
    portal = get_settings().BITRIX_PORTAL_URL.rstrip("/")
    return f"{portal}/crm/deal/details/{bitrix_id}/" if portal else None


def _last_movement(d: CrmDeal) -> datetime | None:
    stamps = [
        _as_utc(t) for t in (d.last_observed_activity_at, d.stage_changed_observed_at, d.date_modify) if t
    ]
    return max(stamps) if stamps else None


def _by_amount(deals: list[DigestDeal]) -> list[DigestDeal]:
    return sorted(deals, key=lambda x: (x.opportunity or Decimal(0)), reverse=True)


async def _data_warning(session: AsyncSession) -> str | None:
    settings = get_settings()
    if not settings.BITRIX_WEBHOOK_URL:
        return "Bitrix не подключён — цифры по последним сохранённым данным."
    state = await SyncRepository(session).get_state("last_deals_sync") or {}
    at = state.get("at")
    if not at:
        return "Синхронизация с Bitrix ещё не выполнялась."
    age = utc_now() - datetime.fromisoformat(at)
    if age > STALE_SYNC_AFTER:
        hours = int(age.total_seconds() // 3600)
        return f"Данные из Bitrix не обновлялись {hours} ч — цифры могут быть устаревшими."
    return None


async def build_digest(session: AsyncSession, *, today: date | None = None) -> Digest:
    settings = get_settings()
    now = utc_now()
    today = today or now.astimezone(app_tz()).date()
    yesterday = today - timedelta(days=1)
    stale_cutoff = now - timedelta(days=settings.DIGEST_STALE_DAYS)
    top_n = settings.DIGEST_TOP_N

    kpis = await compute_period_kpis(session, yesterday, yesterday, include_series=False)

    overdue_rows = (
        await session.execute(overdue_activities_query(now, CrmDeal.id, CrmActivity.bitrix_id))
    ).all()
    overdue_by_deal: dict[int, set[int]] = {}
    for deal_id, activity_bid in overdue_rows:
        overdue_by_deal.setdefault(deal_id, set()).add(activity_bid)

    open_deals = (
        await session.execute(
            select(CrmDeal)
            .where(CrmDeal.closed.is_(False), CrmDeal.missing_from_bitrix.is_(False))
            .options(selectinload(CrmDeal.assigned_manager))
        )
    ).scalars().all()
    managers = (await session.execute(select(CrmManager))).scalars().all()
    by_manager: dict[int, ManagerDigest] = {
        m.id: ManagerDigest(manager_id=m.id, name=_manager_name(m) or f"#{m.bitrix_id}", telegram_chat_id=m.telegram_chat_id)
        for m in managers
    }

    all_idle: list[DigestDeal] = []
    no_future_total = 0
    for d in open_deals:
        moved = _last_movement(d)
        idle_days = (now - moved).days if moved else None
        item = DigestDeal(
            deal_id=d.id,
            bitrix_id=d.bitrix_id,
            title=d.title or f"Сделка {d.bitrix_id}",
            opportunity=d.opportunity,
            manager=_manager_name(d.assigned_manager),
            url=_deal_url(d.bitrix_id),
            overdue_count=len(overdue_by_deal.get(d.id, ())),
            idle_days=idle_days,
        )
        is_idle = moved is not None and moved < stale_cutoff
        if is_idle:
            all_idle.append(item)
        if not d.has_future_activity:
            no_future_total += 1
        md = by_manager.get(d.assigned_by_id) if d.assigned_by_id else None
        if md is None:
            continue
        md.overdue_activities += item.overdue_count
        if item.overdue_count:
            md.overdue_deals.append(item)
        if not d.has_future_activity:
            md.no_future.append(item)
        if is_idle:
            md.idle.append(item)

    for md in by_manager.values():
        md.no_future = _by_amount(md.no_future)
        md.idle = _by_amount(md.idle)
        md.overdue_deals = sorted(md.overdue_deals, key=lambda x: x.overdue_count, reverse=True)

    ranked = sorted(
        (m for m in by_manager.values() if m.has_problems),
        key=lambda m: (m.overdue_activities + len(m.no_future) + len(m.idle)),
        reverse=True,
    )

    return Digest(
        day=today,
        new_yesterday=kpis["new_deals_count"],
        won_yesterday=kpis["won_count"],
        won_sum_yesterday=kpis["sum_won_opportunity"],
        active_deals=len(open_deals),
        overdue_activities=kpis["open_overdue"],
        no_future_count=no_future_total,
        idle_count=len(all_idle),
        stale_days=settings.DIGEST_STALE_DAYS,
        top_n=top_n,
        managers=ranked,
        managers_all=list(by_manager.values()),
        top_idle=_by_amount(all_idle)[:top_n],
        data_warning=await _data_warning(session),
    )


# --- rendering (Telegram HTML parse mode) -------------------------------------------


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


def format_money(value: Decimal | float | None) -> str:
    if value is None:
        return "—"
    return f"{Decimal(value):,.0f}".replace(",", " ") + " ₽"


def _deal_line(d: DigestDeal, *, show_manager: bool, extra: str = "") -> str:
    title = _e(d.title[:80])
    name = f'<a href="{_e(d.url)}">{title}</a>' if d.url else title
    parts = [format_money(d.opportunity)] if d.opportunity else []
    if show_manager and d.manager:
        parts.append(_e(d.manager))
    if extra:
        parts.append(extra)
    return f"• {name}" + (f" — {' · '.join(parts)}" if parts else "")


def _header(digest: Digest, title: str) -> list[str]:
    lines = [f"<b>{_e(title)} · {digest.day.strftime('%d.%m.%Y')}</b>"]
    if digest.data_warning:
        lines.append(f"⚠️ <i>{_e(digest.data_warning)}</i>")
    return lines


def render_team_digest(digest: Digest) -> str:
    lines = _header(digest, "Дайджест отдела продаж")
    lines += [
        "",
        f"Вчера: новых сделок {digest.new_yesterday} · выиграно {digest.won_yesterday}"
        + (f" на {format_money(digest.won_sum_yesterday)}" if digest.won_yesterday else ""),
        f"В работе сейчас: {digest.active_deals}",
        f"🔴 Просроченных дел: {digest.overdue_activities}",
        f"🟠 Сделок без следующего дела: {digest.no_future_count}",
        f"⏸ Без движения {digest.stale_days}+ дн.: {digest.idle_count}",
    ]
    if digest.managers:
        lines += ["", "<b>По менеджерам</b>"]
        for m in digest.managers:
            lines.append(
                f"{_e(m.name)} — просрочено {m.overdue_activities} · без дела {len(m.no_future)}"
                f" · стоят {len(m.idle)}"
            )
    else:
        lines += ["", "Проблемных сделок нет 👍"]
    if digest.top_idle:
        lines += ["", f"<b>Крупные сделки без движения {digest.stale_days}+ дн.</b>"]
        lines += [
            _deal_line(d, show_manager=True, extra=f"{d.idle_days} дн." if d.idle_days is not None else "")
            for d in digest.top_idle
        ]
    return "\n".join(lines)


def render_manager_digest(digest: Digest, m: ManagerDigest) -> str:
    n = digest.top_n
    lines = _header(digest, f"Ваши сделки, {m.name}")
    lines += [
        "",
        f"🔴 Просроченных дел: {m.overdue_activities}",
        f"🟠 Сделок без следующего дела: {len(m.no_future)}",
        f"⏸ Без движения {digest.stale_days}+ дн.: {len(m.idle)}",
    ]
    sections = (
        ("Просроченные дела", m.overdue_deals, lambda d: f"просрочено {d.overdue_count}"),
        ("Нет следующего дела", m.no_future, lambda d: ""),
        (f"Без движения {digest.stale_days}+ дн.", m.idle, lambda d: f"{d.idle_days} дн."),
    )
    for title, deals, extra in sections:
        if not deals:
            continue
        lines += ["", f"<b>{_e(title)}</b>"]
        lines += [_deal_line(d, show_manager=False, extra=extra(d)) for d in deals[:n]]
        if len(deals) > n:
            lines.append(f"…и ещё {len(deals) - n}")
    if not m.has_problems:
        lines += ["", "Всё в порядке 👍"]
    return "\n".join(lines)


_TAG_RE = re.compile(r"<[^>]+>")


def to_plain_text(telegram_html: str) -> str:
    """Preview-safe plain text (no markup reaches the browser)."""
    return html.unescape(_TAG_RE.sub("", telegram_html))

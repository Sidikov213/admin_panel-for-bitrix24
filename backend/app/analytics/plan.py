"""Plan vs fact for sales targets: won amount or profit, run-rate forecast, pace status."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.card_quality import resolved_field_hints
from app.analytics.kpi import _as_utc
from app.core.timezone import app_tz, local_day_bounds
from app.models.crm import CrmDeal, CrmManager, CrmStage
from app.models.sync import SalesTarget
from app.repositories.sync import SyncRepository
from app.services.sync_service import DEAL_FIELDS_STATE

# Forecast within this share below the plan is "at risk", below it is "behind"
AT_RISK_SHARE = Decimal("0.9")
# Run-rate from the first days is noise (one deal on day 2 → "600% forecast"):
# trust it only after this share of the period, and never before MIN_FORECAST_DAYS
MIN_FORECAST_SHARE = 0.2
MIN_FORECAST_DAYS = 3


@dataclass
class TargetProgress:
    target_id: int
    manager_id: int | None
    manager_name: str | None
    period_type: str
    period_start: date
    period_end: date
    currency: str
    plan: Decimal
    fact: Decimal
    won_count: int
    percent: float
    expected: Decimal
    forecast: Decimal
    forecast_percent: float
    forecast_reliable: bool
    # Days until the forecast becomes reliable (0 when it already is)
    forecast_in_days: int
    remaining: Decimal
    days_total: int
    days_elapsed: int
    days_left: int
    per_day_needed: Decimal | None
    # done | on_track | at_risk | behind | missed | not_started | early
    status: str
    active: bool
    # revenue | profit. Last and defaulted: reports stored before it existed are rebuilt from JSON
    metric: str = "revenue"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, Decimal):
                d[k] = float(v)
            elif isinstance(v, date):
                d[k] = v.isoformat()
        return d


def _money(v: Decimal) -> Decimal:
    return v.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _pct(part: Decimal, whole: Decimal) -> float:
    return round(float(part / whole * 100), 1) if whole > 0 else 0.0


async def profit_field_code(session: AsyncSession) -> str | None:
    """The Bitrix deal field managers type the profit into (found by its label)."""
    fields = await SyncRepository(session).get_state(DEAL_FIELDS_STATE) or {}
    return (await resolved_field_hints(session, fields)).get("profit")


_NUMBER_RE = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")


def parse_profit(value: object) -> Decimal:
    """The profit field is free text: «25 000», «25000,50»; «неизвестно» and blanks count as 0."""
    text = str(value or "").replace(" ", "").replace(" ", "").replace(",", ".")
    return Decimal(text) if _NUMBER_RE.match(text) else Decimal(0)


def _amount_columns(metric: str, profit_code: str | None) -> list:
    """Columns one won deal's contribution is read from (see _amount)."""
    if metric == "profit":
        return [CrmDeal.raw[profit_code].astext] if profit_code else [literal(None)]
    return [CrmDeal.opportunity]


def _amount(metric: str, value: object) -> Decimal:
    if metric == "profit":
        return parse_profit(value)
    return Decimal(str(value)) if value is not None else Decimal(0)


def _won_filters(start: date, end: date) -> list:
    start_utc, _ = local_day_bounds(start)
    _, end_utc = local_day_bounds(end)
    closed_at = func.coalesce(CrmDeal.closedate, CrmDeal.date_modify)
    return [
        CrmDeal.closed.is_(True),
        CrmDeal.missing_from_bitrix.is_(False),
        CrmDeal.is_excluded.is_(False),
        CrmStage.semantics == "success",
        closed_at >= start_utc,
        closed_at <= end_utc,
    ]


async def won_totals(
    session: AsyncSession, start: date, end: date, *, metric: str = "revenue", profit_code: str | None = None
) -> tuple[dict[int | None, tuple[Decimal, int]], tuple[Decimal, int]]:
    """Won amount (or profit) and count per manager and in total for local calendar days [start, end].

    Same rule as KPI "won": closed, stage semantics success, CLOSEDATE (date_modify
    fallback) inside the period, deals missing from Bitrix excluded.
    """
    # Summed here, not in SQL: the profit is typed as free text
    rows = (
        await session.execute(
            select(CrmDeal.assigned_by_id, *_amount_columns(metric, profit_code))
            .join(CrmStage, CrmDeal.stage_id == CrmStage.id)
            .where(*_won_filters(start, end))
        )
    ).all()
    per_manager: dict[int | None, tuple[Decimal, int]] = {}
    for mid, value in rows:
        amount, count = per_manager.get(mid, (Decimal(0), 0))
        per_manager[mid] = (amount + _amount(metric, value), count + 1)
    total = (
        sum((v[0] for v in per_manager.values()), Decimal(0)),
        sum(v[1] for v in per_manager.values()),
    )
    return per_manager, total


def compute_progress(
    target: SalesTarget,
    *,
    fact: Decimal,
    won_count: int,
    on: date,
    manager_name: str | None,
) -> TargetProgress:
    plan = Decimal(target.amount)
    days_total = (target.period_end - target.period_start).days + 1
    # The current day counts as elapsed: today's wins are already in the fact
    days_elapsed = max(0, min(days_total, (on - target.period_start).days + 1))
    days_left = days_total - days_elapsed
    share = Decimal(days_elapsed) / Decimal(days_total)
    expected = plan * share
    if days_elapsed == 0:
        forecast = Decimal(0)
    elif days_left == 0:
        forecast = fact
    else:
        forecast = fact / share
    remaining = max(plan - fact, Decimal(0))
    reliable_after = max(MIN_FORECAST_DAYS, math.ceil(days_total * MIN_FORECAST_SHARE))
    reliable_after = min(reliable_after, days_total)
    forecast_reliable = days_elapsed >= reliable_after

    if days_elapsed == 0:
        status = "not_started"
    elif fact >= plan:
        status = "done"
    elif days_left == 0:
        status = "missed"
    elif not forecast_reliable:
        status = "early"
    elif forecast >= plan:
        status = "on_track"
    elif forecast >= plan * AT_RISK_SHARE:
        status = "at_risk"
    else:
        status = "behind"

    return TargetProgress(
        target_id=target.id,
        manager_id=target.manager_id,
        manager_name=manager_name,
        period_type=target.period_type.value if hasattr(target.period_type, "value") else str(target.period_type),
        period_start=target.period_start,
        period_end=target.period_end,
        currency=target.currency,
        plan=_money(plan),
        fact=_money(fact),
        won_count=won_count,
        percent=_pct(fact, plan),
        expected=_money(expected),
        forecast=_money(forecast),
        forecast_percent=_pct(forecast, plan),
        forecast_reliable=forecast_reliable,
        forecast_in_days=max(0, reliable_after - days_elapsed),
        remaining=_money(remaining),
        days_total=days_total,
        days_elapsed=days_elapsed,
        days_left=days_left,
        per_day_needed=_money(remaining / days_left) if days_left and remaining else None,
        status=status,
        active=target.period_start <= on <= target.period_end,
        metric=target.metric or "revenue",
    )


async def targets_progress(
    session: AsyncSession,
    on: date,
    *,
    active_only: bool = True,
    manager_id: int | None = None,
) -> list[TargetProgress]:
    """Progress of every target (or those active on `on`). Department target (no manager) first."""
    stmt = select(SalesTarget)
    if active_only:
        stmt = stmt.where(SalesTarget.period_start <= on, SalesTarget.period_end >= on)
    if manager_id is not None:
        stmt = stmt.where(SalesTarget.manager_id == manager_id)
    targets = (await session.execute(stmt)).scalars().all()
    if not targets:
        return []

    manager_ids = {t.manager_id for t in targets if t.manager_id is not None}
    names: dict[int, str] = {}
    if manager_ids:
        rows = (await session.execute(select(CrmManager).where(CrmManager.id.in_(manager_ids)))).scalars().all()
        names = {m.id: f"{m.last_name} {m.name}".strip() for m in rows}

    # One aggregate query per distinct period instead of one per target
    profit_code = await profit_field_code(session) if any(t.metric == "profit" for t in targets) else None
    totals_cache: dict[tuple[date, date, str], tuple[dict, tuple[Decimal, int]]] = {}
    result: list[TargetProgress] = []
    for t in targets:
        metric = t.metric or "revenue"
        key = (t.period_start, t.period_end, metric)
        if key not in totals_cache:
            totals_cache[key] = await won_totals(
                session, t.period_start, t.period_end, metric=metric, profit_code=profit_code
            )
        per_manager, total = totals_cache[key]
        fact, count = total if t.manager_id is None else per_manager.get(t.manager_id, (Decimal(0), 0))
        result.append(
            compute_progress(
                t,
                fact=fact,
                won_count=count,
                on=on,
                manager_name=names.get(t.manager_id) if t.manager_id is not None else None,
            )
        )
    result.sort(key=lambda p: (p.manager_id is not None, not p.active, p.period_start, p.percent))
    return result


async def target_series(session: AsyncSession, target: SalesTarget, on: date) -> dict[str, Any]:
    """Day by day: the fact accumulated so far against the even pace to the plan."""
    metric = target.metric or "revenue"
    profit_code = await profit_field_code(session) if metric == "profit" else None
    closed_at = func.coalesce(CrmDeal.closedate, CrmDeal.date_modify)
    stmt = (
        select(closed_at, *_amount_columns(metric, profit_code))
        .join(CrmStage, CrmDeal.stage_id == CrmStage.id)
        .where(*_won_filters(target.period_start, target.period_end))
    )
    if target.manager_id is not None:
        stmt = stmt.where(CrmDeal.assigned_by_id == target.manager_id)
    tz = app_tz()
    per_day: dict[date, Decimal] = {}
    for at, value in (await session.execute(stmt)).all():
        day = _as_utc(at).astimezone(tz).date()
        per_day[day] = per_day.get(day, Decimal(0)) + _amount(metric, value)

    plan = Decimal(target.amount)
    days_total = (target.period_end - target.period_start).days + 1
    points: list[dict[str, Any]] = []
    total = Decimal(0)
    for i in range(days_total):
        day = target.period_start + timedelta(days=i)
        total += per_day.get(day, Decimal(0))
        points.append(
            {
                "date": day.isoformat(),
                "pace": float(_money(plan * (i + 1) / days_total)),
                # The future has no fact yet: the line stops at today
                "fact": float(_money(total)) if day <= on else None,
            }
        )
    return {"target_id": target.id, "metric": metric, "plan": float(_money(plan)), "points": points}

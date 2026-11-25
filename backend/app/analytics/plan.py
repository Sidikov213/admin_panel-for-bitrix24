"""Plan vs fact for sales targets: won amount or profit, run-rate forecast, pace status."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from types import SimpleNamespace
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
# Stages whose deals are as good as sold once the mount is scheduled (matched by name:
# the ids differ between portals). Won deals are added by stage semantics
SCHEDULED_STAGE_HINTS = ("поставлен в график", "итоговую оплату")


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
    # Won + scheduled + awaiting payment, by mount date inside the period. None: no mount date field
    scheduled: Decimal | None = None
    scheduled_count: int = 0
    scheduled_percent: float = 0.0
    # Not a stored target: the sum of the managers' plans for a period without a department plan
    virtual: bool = False

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


async def mount_field_code(session: AsyncSession) -> str | None:
    fields = await SyncRepository(session).get_state(DEAL_FIELDS_STATE) or {}
    return (await resolved_field_hints(session, fields)).get("mount_date")


async def scheduled_stage_ids(session: AsyncSession) -> list[int]:
    # Matched here, not in SQL: SQLite's lower() leaves Cyrillic as is
    rows = (await session.execute(select(CrmStage.id, CrmStage.name, CrmStage.semantics))).all()
    return [
        sid
        for sid, name, semantics in rows
        if semantics == "success" or any(h in (name or "").lower() for h in SCHEDULED_STAGE_HINTS)
    ]


async def scheduled_totals(
    session: AsyncSession,
    start: date,
    end: date,
    *,
    metric: str = "revenue",
    profit_code: str | None = None,
    mount_code: str,
    stage_ids: list[int],
) -> tuple[dict[int | None, tuple[Decimal, int]], tuple[Decimal, int]]:
    """What the period brings if every scheduled mount is done and paid: deals that are won,
    scheduled or awaiting the final payment, with the mount date inside [start, end]."""
    # The mount date is an ISO string («2026-11-25T03:00:00+03:00»), so text comparison orders it
    mount = CrmDeal.raw[mount_code].astext
    rows = (
        await session.execute(
            select(CrmDeal.assigned_by_id, *_amount_columns(metric, profit_code)).where(
                CrmDeal.stage_id.in_(stage_ids),
                CrmDeal.missing_from_bitrix.is_(False),
                CrmDeal.is_excluded.is_(False),
                mount >= start.isoformat(),
                mount < (end + timedelta(days=1)).isoformat(),
            )
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
    scheduled: tuple[Decimal, int] | None = None,
    virtual: bool = False,
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
        scheduled=_money(scheduled[0]) if scheduled else None,
        scheduled_count=scheduled[1] if scheduled else 0,
        scheduled_percent=_pct(scheduled[0], plan) if scheduled else 0.0,
        virtual=virtual,
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
    mount_code = await mount_field_code(session)
    stage_ids = await scheduled_stage_ids(session) if mount_code else []
    totals_cache: dict[tuple[date, date, str], tuple[dict, tuple[Decimal, int]]] = {}
    scheduled_cache: dict[tuple[date, date, str], tuple[dict, tuple[Decimal, int]]] = {}
    result: list[TargetProgress] = []
    # (period, metric, currency) → manager targets with their numbers, for the department sum
    groups: dict[tuple, list[tuple[SalesTarget, Decimal, int, tuple[Decimal, int] | None]]] = {}
    with_department: set[tuple] = set()
    for t in targets:
        metric = t.metric or "revenue"
        key = (t.period_start, t.period_end, metric)
        if key not in totals_cache:
            totals_cache[key] = await won_totals(
                session, t.period_start, t.period_end, metric=metric, profit_code=profit_code
            )
        per_manager, total = totals_cache[key]
        fact, count = total if t.manager_id is None else per_manager.get(t.manager_id, (Decimal(0), 0))
        scheduled: tuple[Decimal, int] | None = None
        if mount_code and stage_ids:
            if key not in scheduled_cache:
                scheduled_cache[key] = await scheduled_totals(
                    session,
                    t.period_start,
                    t.period_end,
                    metric=metric,
                    profit_code=profit_code,
                    mount_code=mount_code,
                    stage_ids=stage_ids,
                )
            s_per_manager, s_total = scheduled_cache[key]
            scheduled = s_total if t.manager_id is None else s_per_manager.get(t.manager_id, (Decimal(0), 0))
        group = (t.period_type, t.period_start, t.period_end, metric, t.currency)
        if t.manager_id is None:
            with_department.add(group)
        else:
            groups.setdefault(group, []).append((t, fact, count, scheduled))
        result.append(
            compute_progress(
                t,
                fact=fact,
                won_count=count,
                on=on,
                manager_name=names.get(t.manager_id) if t.manager_id is not None else None,
                scheduled=scheduled,
            )
        )
    # No department plan for the period: show the managers' plans added up instead
    if manager_id is None:
        for n, (group, members) in enumerate(sorted(groups.items(), key=lambda g: g[0][1]), start=1):
            if group in with_department or len(members) < 2:
                continue
            period_type, start, end, metric, currency = group
            scheduled_sum = None
            if all(m[3] is not None for m in members):
                scheduled_sum = (sum((m[3][0] for m in members), Decimal(0)), sum(m[3][1] for m in members))
            result.append(
                compute_progress(
                    SimpleNamespace(
                        id=-n,
                        manager_id=None,
                        period_type=period_type,
                        period_start=start,
                        period_end=end,
                        currency=currency,
                        amount=sum((Decimal(m[0].amount) for m in members), Decimal(0)),
                        metric=metric,
                    ),
                    fact=sum((m[1] for m in members), Decimal(0)),
                    won_count=sum(m[2] for m in members),
                    on=on,
                    manager_name=None,
                    scheduled=scheduled_sum,
                    virtual=True,
                )
            )
    result.sort(key=lambda p: (p.manager_id is not None, not p.active, p.period_start, p.percent))
    return result


async def target_series(session: AsyncSession, target: SalesTarget, on: date) -> dict[str, Any]:
    """Day by day: the fact accumulated so far against the even pace to the plan."""
    return await _series(
        session,
        target_id=target.id,
        start=target.period_start,
        end=target.period_end,
        metric=target.metric or "revenue",
        plan=Decimal(target.amount),
        manager_ids=None if target.manager_id is None else [target.manager_id],
        on=on,
    )


async def department_series(session: AsyncSession, start: date, end: date, metric: str, on: date) -> dict[str, Any] | None:
    """The same chart for the managers' plans of one period added up (see targets_progress)."""
    targets = (
        (
            await session.execute(
                select(SalesTarget).where(
                    SalesTarget.manager_id.is_not(None),
                    SalesTarget.period_start == start,
                    SalesTarget.period_end == end,
                    SalesTarget.metric == metric,
                )
            )
        )
        .scalars()
        .all()
    )
    if not targets:
        return None
    return await _series(
        session,
        target_id=None,
        start=start,
        end=end,
        metric=metric,
        plan=sum((Decimal(t.amount) for t in targets), Decimal(0)),
        manager_ids=[t.manager_id for t in targets],
        on=on,
    )


async def _series(
    session: AsyncSession,
    *,
    target_id: int | None,
    start: date,
    end: date,
    metric: str,
    plan: Decimal,
    manager_ids: list[int] | None,
    on: date,
) -> dict[str, Any]:
    target = SimpleNamespace(id=target_id, period_start=start, period_end=end, amount=plan)
    profit_code = await profit_field_code(session) if metric == "profit" else None
    closed_at = func.coalesce(CrmDeal.closedate, CrmDeal.date_modify)
    stmt = (
        select(closed_at, *_amount_columns(metric, profit_code))
        .join(CrmStage, CrmDeal.stage_id == CrmStage.id)
        .where(*_won_filters(target.period_start, target.period_end))
    )
    if manager_ids is not None:
        stmt = stmt.where(CrmDeal.assigned_by_id.in_(manager_ids))
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

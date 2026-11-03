"""Pipeline funnel and deal velocity: stage conversion, time in stage, cycle length, win rate.

Stage paths come from Bitrix stage history (exact timestamps) when available, otherwise
from stage changes observed by polling, otherwise only the current stage is known.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.kpi import _as_utc
from app.core.timezone import local_day_bounds, utc_now
from app.models.crm import CrmDeal, CrmManager, CrmPipeline, CrmStage, DealChangeEvent, DealStageHistory

_CHUNK = 1000
SECONDS_PER_DAY = 86400


@dataclass
class _Deal:
    deal: CrmDeal
    # (entered_at, stage bitrix id), chronological
    path: list[tuple[datetime, str]] = field(default_factory=list)
    source: str = "none"  # bitrix | observed | none


def _days(seconds: float) -> float:
    return round(seconds / SECONDS_PER_DAY, 1)


def _stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"median_days": None, "avg_days": None, "count": 0}
    return {
        "median_days": _days(statistics.median(values)),
        "avg_days": _days(statistics.fmean(values)),
        "count": len(values),
    }


def _closed_at(d: CrmDeal) -> datetime | None:
    return _as_utc(d.closedate or d.date_modify)


async def _chunked(session: AsyncSession, stmt_for_chunk, ids: list[int]) -> list[Any]:
    rows: list[Any] = []
    for i in range(0, len(ids), _CHUNK):
        rows.extend((await session.execute(stmt_for_chunk(ids[i : i + _CHUNK]))).scalars().all())
    return rows


async def _build_paths(session: AsyncSession, deals: list[CrmDeal], stage_by_pk: dict[int, CrmStage]) -> list[_Deal]:
    by_bitrix = {d.bitrix_id: _Deal(deal=d) for d in deals}
    history = await _chunked(
        session,
        lambda chunk: select(DealStageHistory)
        .where(DealStageHistory.deal_bitrix_id.in_(chunk))
        .order_by(DealStageHistory.created_time, DealStageHistory.bitrix_id),
        list(by_bitrix),
    )
    for h in history:
        item = by_bitrix.get(h.deal_bitrix_id)
        if item is not None:
            item.path.append((_as_utc(h.created_time), h.stage_bitrix_id))
            item.source = "bitrix"

    # Fallback: stage changes observed by polling (stage_id values are internal ids)
    no_history = {d.deal.id: d for d in by_bitrix.values() if not d.path}
    if no_history:
        events = await _chunked(
            session,
            lambda chunk: select(DealChangeEvent)
            .where(DealChangeEvent.deal_id.in_(chunk), DealChangeEvent.field_name == "stage_id")
            .order_by(DealChangeEvent.observed_at),
            list(no_history),
        )
        for ev in events:
            item = no_history[ev.deal_id]
            if not item.path and ev.old_value and ev.old_value.isdigit():
                old = stage_by_pk.get(int(ev.old_value))
                created = _as_utc(item.deal.date_create)
                if old is not None and created is not None:
                    item.path.append((created, old.bitrix_id))
            new = stage_by_pk.get(int(ev.new_value)) if ev.new_value and ev.new_value.isdigit() else None
            if new is not None:
                item.path.append((_as_utc(ev.bitrix_event_at or ev.observed_at), new.bitrix_id))
                item.source = "observed"

    for item in by_bitrix.values():
        if item.source == "observed":
            # bitrix_event_at (deal DATE_MODIFY) can predate the previous observation
            item.path.sort(key=lambda p: p[0])
        current = stage_by_pk.get(item.deal.stage_id) if item.deal.stage_id else None
        if current is None:
            continue
        if not item.path:
            created = _as_utc(item.deal.date_create) or _as_utc(item.deal.observed_at) or utc_now()
            item.path.append((created, current.bitrix_id))
        elif item.path[-1][1] != current.bitrix_id:
            # History is behind the deal row: the current stage was entered after the last known move
            moved = _as_utc(item.deal.stage_changed_observed_at) or item.path[-1][0]
            item.path.append((max(moved, item.path[-1][0]), current.bitrix_id))
    return list(by_bitrix.values())


async def compute_funnel(
    session: AsyncSession,
    *,
    category_id: int,
    period_start: date,
    period_end: date,
    manager_id: int | None = None,
) -> dict[str, Any]:
    start_utc, _ = local_day_bounds(period_start)
    _, end_utc = local_day_bounds(period_end)
    now = utc_now()

    pipeline = (
        await session.execute(select(CrmPipeline).where(CrmPipeline.bitrix_id == category_id))
    ).scalar_one_or_none()
    stages = (
        (
            await session.execute(
                select(CrmStage).where(CrmStage.pipeline_id == pipeline.id).order_by(CrmStage.sort, CrmStage.id)
            )
        )
        .scalars()
        .all()
        if pipeline
        else []
    )
    stage_by_pk = {s.id: s for s in stages}
    stage_by_bid = {s.bitrix_id: s for s in stages}
    process = [s for s in stages if s.semantics not in ("success", "failure")]
    process_rank = {s.bitrix_id: i for i, s in enumerate(process)}

    filters = [CrmDeal.category_id == category_id, CrmDeal.missing_from_bitrix.is_(False)]
    if manager_id is not None:
        filters.append(CrmDeal.assigned_by_id == manager_id)
    deals = (await session.execute(select(CrmDeal).where(*filters))).scalars().all()
    items = await _build_paths(session, list(deals), stage_by_pk)

    def semantics_of(item: _Deal) -> str | None:
        s = stage_by_pk.get(item.deal.stage_id) if item.deal.stage_id else None
        return s.semantics if s else None

    def in_period(ts: datetime | None) -> bool:
        return ts is not None and start_utc <= ts <= end_utc

    # --- funnel over the cohort of deals created in the period -----------------------
    cohort = [i for i in items if in_period(_as_utc(i.deal.date_create))]
    reached = [0] * len(process)
    won_in_cohort = 0
    for item in cohort:
        is_won = semantics_of(item) == "success"
        won_in_cohort += is_won
        ranks = [process_rank[st] for _, st in item.path if st in process_rank]
        # Every created deal entered the funnel, even if no in-progress stage is on record
        top = len(process) - 1 if is_won else max(ranks, default=0)
        for r in range(top + 1):
            reached[r] += 1
    funnel = []
    first = reached[0] if reached else 0
    for idx, s in enumerate(process):
        prev = reached[idx - 1] if idx else None
        funnel.append(
            {
                "stage_id": s.bitrix_id,
                "name": s.name,
                "reached": reached[idx],
                "conversion_from_prev": round(reached[idx] / prev * 100, 1) if prev else None,
                "conversion_from_start": round(reached[idx] / first * 100, 1) if first else None,
            }
        )
    last_reached = reached[-1] if reached else 0
    funnel.append(
        {
            "stage_id": "WON",
            "name": "Успешно",
            "reached": won_in_cohort,
            "conversion_from_prev": round(won_in_cohort / last_reached * 100, 1) if last_reached else None,
            "conversion_from_start": round(won_in_cohort / first * 100, 1) if first else None,
            "kind": "won",
        }
    )

    # --- time in stage: stays that ended inside the period, plus deals sitting there now --
    exited: dict[str, list[float]] = {s.bitrix_id: [] for s in process}
    current_age: dict[str, list[float]] = {s.bitrix_id: [] for s in process}
    for item in items:
        path = item.path
        for (entered, stage), (left, _next) in zip(path, path[1:]):
            if stage in exited and in_period(left) and left >= entered:
                exited[stage].append((left - entered).total_seconds())
        if path and not item.deal.closed and path[-1][1] in current_age:
            current_age[path[-1][1]].append((now - path[-1][0]).total_seconds())
    stage_time = []
    for s in process:
        cur = current_age[s.bitrix_id]
        stage_time.append(
            {
                "stage_id": s.bitrix_id,
                "name": s.name,
                **_stats(exited[s.bitrix_id]),
                "current_count": len(cur),
                "current_median_days": _days(statistics.median(cur)) if cur else None,
            }
        )

    # --- outcomes of deals closed in the period --------------------------------------
    closed = [i for i in items if i.deal.closed and in_period(_closed_at(i.deal))]
    won = [i for i in closed if semantics_of(i) == "success"]
    lost = [i for i in closed if semantics_of(i) == "failure"]

    def cycle(group: list[_Deal]) -> list[float]:
        out = []
        for i in group:
            created, ended = _as_utc(i.deal.date_create), _closed_at(i.deal)
            if created and ended and ended >= created:
                out.append((ended - created).total_seconds())
        return out

    loss_counts: dict[str, int] = {}
    for i in lost:
        before = [st for _, st in i.path if st in process_rank]
        key = before[-1] if before else "unknown"
        loss_counts[key] = loss_counts.get(key, 0) + 1
    losses = sorted(
        (
            {
                "stage_id": k,
                "name": stage_by_bid[k].name if k in stage_by_bid else "Неизвестно",
                "count": v,
                "share": round(v / len(lost) * 100, 1),
            }
            for k, v in loss_counts.items()
        ),
        key=lambda x: -x["count"],
    )

    won_amounts = [i.deal.opportunity for i in won if i.deal.opportunity is not None]
    decided = len(won) + len(lost)
    summary = {
        "created": len(cohort),
        "won": len(won),
        "lost": len(lost),
        "win_rate": round(len(won) / decided * 100, 1) if decided else None,
        "won_amount": float(sum(won_amounts, Decimal(0))),
        "avg_won_amount": float(sum(won_amounts, Decimal(0)) / len(won_amounts)) if won_amounts else None,
        "cycle_won": _stats(cycle(won)),
        "cycle_lost": _stats(cycle(lost)),
    }

    # --- per manager (whole pipeline view only) --------------------------------------
    managers_out: list[dict[str, Any]] = []
    if manager_id is None:
        mids = {i.deal.assigned_by_id for i in items if i.deal.assigned_by_id}
        names = {}
        if mids:
            rows = (await session.execute(select(CrmManager).where(CrmManager.id.in_(mids)))).scalars().all()
            names = {m.id: f"{m.last_name} {m.name}".strip() for m in rows}
        for mid in mids:
            m_cohort = [i for i in cohort if i.deal.assigned_by_id == mid]
            m_won = [i for i in won if i.deal.assigned_by_id == mid]
            m_lost = [i for i in lost if i.deal.assigned_by_id == mid]
            if not (m_cohort or m_won or m_lost):
                continue
            m_decided = len(m_won) + len(m_lost)
            amounts = [i.deal.opportunity for i in m_won if i.deal.opportunity is not None]
            managers_out.append(
                {
                    "manager_id": mid,
                    "name": names.get(mid, f"#{mid}"),
                    "created": len(m_cohort),
                    "won": len(m_won),
                    "lost": len(m_lost),
                    "win_rate": round(len(m_won) / m_decided * 100, 1) if m_decided else None,
                    "won_amount": float(sum(amounts, Decimal(0))),
                    "cycle_won_median_days": _stats(cycle(m_won))["median_days"],
                }
            )
        managers_out.sort(key=lambda m: (-m["won_amount"], -m["won"]))

    # --- data quality ----------------------------------------------------------------
    considered = {id(i): i for i in [*cohort, *closed]}.values()
    sources = [i.source for i in considered]
    total = len(sources)
    bitrix_share = round(sources.count("bitrix") / total * 100, 1) if total else None
    if not total:
        source, note = "none", None
    elif sources.count("bitrix") == total:
        source, note = "bitrix", None
    elif sources.count("bitrix"):
        source, note = "mixed", f"История этапов из Bitrix есть для {bitrix_share}% сделок, для остальных — по наблюдениям синхронизации."
    elif sources.count("observed"):
        source, note = (
            "observed",
            "История этапов из Bitrix недоступна — переходы восстановлены по изменениям, замеченным при синхронизации; время на этапах приблизительное.",
        )
    else:
        source, note = "none", "Истории переходов нет — воронка построена только по текущим этапам сделок."

    return {
        "pipeline": {"category_id": category_id, "name": pipeline.name if pipeline else f"Воронка {category_id}"},
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "manager_id": manager_id,
        "funnel": funnel,
        "stage_time": stage_time,
        "summary": summary,
        "losses": losses,
        "managers": managers_out,
        "data_quality": {"source": source, "history_coverage": bitrix_share, "note": note},
        "definitions": {
            "funnel": "Сделки, созданные в периоде: сколько дошли до этапа или дальше (успешные — до конца воронки).",
            "stage_time": "Сколько сделки пробыли на этапе — по переходам, завершившимся в периоде. «Сейчас» — открытые сделки на этапе.",
            "win_rate": "Выиграно / (выиграно + проиграно) среди сделок, закрытых в периоде.",
            "cycle": "От создания сделки до закрытия (CLOSEDATE, иначе дата изменения).",
            "losses": "Этап, на котором была сделка перед проигрышем.",
        },
        "computed_at": now.isoformat(),
    }

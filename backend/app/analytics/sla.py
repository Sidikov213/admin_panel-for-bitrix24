"""Stage deadlines ("зависла на этапе") and reaction speed on new leads.

Deadlines come from the sales department (ТЗ, ноябрь 2026): defaults are matched by stage
name, an admin can override any stage in the panel. Hour-level deadlines count working
time only (see app.core.work_calendar); day-level ones count calendar days by default.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analytics.funnel import _build_paths
from app.analytics.kpi import _as_utc
from app.core.timezone import local_day_bounds, utc_now
from app.core.work_calendar import WorkCalendar, get_work_calendar
from app.integrations.bitrix.links import activity_type_label, deal_url
from app.models.crm import CrmActivity, CrmDeal, CrmManager, CrmPipeline, CrmStage, DealStageHistory, StageSlaRule

UNITS = ("work_hours", "work_days", "calendar_days")
UNIT_LABELS = {"work_hours": "раб. ч", "work_days": "раб. дн.", "calendar_days": "дн."}
_CHUNK = 1000

# First match wins. Keywords are matched in the lower-cased stage name.
# Values: answers to ТЗ §15 «Через сколько времени сделка на каждом этапе считается зависшей?»
DEFAULT_RULES: list[tuple[tuple[str, ...], float | None, str, bool]] = [
    (("пробное бурение", "подготовка к монтажу"), None, "calendar_days", False),
    (("не обработан", "новая заявка"), 1, "work_hours", True),
    (("взят в работу",), 1, "work_hours", True),
    (("недозвон",), 7, "calendar_days", False),
    (("квалификац", "контакт установлен"), 10, "calendar_days", False),
    (("кп с расч",), 10, "calendar_days", False),
    # Before «монтаж»: the real name is «Ждем итоговую оплату после монтажа (безнал)»
    (("итоговую оплату", "ждем оплат", "ждём оплат"), 7, "calendar_days", False),
    (("поставлен в график", "монтаж"), 30, "calendar_days", False),
]


@dataclass
class Rule:
    stage_bitrix_id: str
    stage_name: str
    category_id: int
    pipeline_name: str
    sort: int
    threshold: float | None
    unit: str
    reaction_stage: bool
    source: str  # default | custom | none

    @property
    def tracked(self) -> bool:
        return self.threshold is not None

    def limit_seconds(self, cal: WorkCalendar) -> float | None:
        if self.threshold is None:
            return None
        if self.unit == "work_hours":
            return self.threshold * 3600
        if self.unit == "work_days":
            return self.threshold * cal.day_seconds
        return self.threshold * 86400

    def elapsed(self, cal: WorkCalendar, start: datetime, end: datetime) -> float:
        if self.unit in ("work_hours", "work_days"):
            return cal.work_seconds(start, end)
        return max(0.0, (end - start).total_seconds())

    def label(self) -> str:
        if self.threshold is None:
            return "не отслеживается"
        value = f"{self.threshold:g}".replace(".", ",")
        return f"{value} {UNIT_LABELS[self.unit]}"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "label": self.label(), "tracked": self.tracked}


def default_rule(stage_name: str) -> tuple[float | None, str, bool, bool]:
    """(threshold, unit, reaction_stage, matched)"""
    name = stage_name.lower()
    for keywords, threshold, unit, reaction in DEFAULT_RULES:
        if any(k in name for k in keywords):
            return threshold, unit, reaction, True
    return None, "calendar_days", False, False


async def load_rules(session: AsyncSession) -> dict[str, Rule]:
    """Rules for every in-progress stage of every synced pipeline."""
    stages = (
        await session.execute(
            select(CrmStage, CrmPipeline)
            .join(CrmPipeline, CrmPipeline.id == CrmStage.pipeline_id)
            .where(CrmStage.semantics.is_(None) | CrmStage.semantics.notin_(("success", "failure")))
            .order_by(CrmPipeline.sort, CrmPipeline.id, CrmStage.sort, CrmStage.id)
        )
    ).all()
    custom = {r.stage_bitrix_id: r for r in (await session.execute(select(StageSlaRule))).scalars()}
    rules: dict[str, Rule] = {}
    for stage, pipe in stages:
        threshold, unit, reaction, matched = default_rule(stage.name)
        source = "default" if matched and threshold is not None else "none"
        override = custom.get(stage.bitrix_id)
        if override is not None:
            threshold = float(override.threshold) if override.threshold is not None else None
            unit, reaction, source = override.unit, override.reaction_stage, "custom"
        rules[stage.bitrix_id] = Rule(
            stage_bitrix_id=stage.bitrix_id,
            stage_name=stage.name,
            category_id=pipe.bitrix_id,
            pipeline_name=pipe.name,
            sort=stage.sort,
            threshold=threshold,
            unit=unit,
            reaction_stage=reaction,
            source=source,
        )
    return rules


def _manager_name(m: CrmManager | None) -> str | None:
    return f"{m.last_name} {m.name}".strip() if m else None


async def _chunked(session: AsyncSession, make_stmt, ids: list[int]) -> list[Any]:
    out: list[Any] = []
    for i in range(0, len(ids), _CHUNK):
        out.extend((await session.execute(make_stmt(ids[i : i + _CHUNK]))).scalars().all())
    return out


async def stuck_deals(
    session: AsyncSession,
    *,
    category_id: int | None = None,
    manager_id: int | None = None,
    only_stuck: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or utc_now()
    cal = get_work_calendar()
    rules = await load_rules(session)

    filters = [CrmDeal.closed.is_(False), CrmDeal.missing_from_bitrix.is_(False)]
    if category_id is not None:
        filters.append(CrmDeal.category_id == category_id)
    if manager_id is not None:
        filters.append(CrmDeal.assigned_by_id == manager_id)
    deals = (
        await session.execute(
            select(CrmDeal).where(*filters).options(selectinload(CrmDeal.stage), selectinload(CrmDeal.assigned_manager))
        )
    ).scalars().all()
    bids = [d.bitrix_id for d in deals]

    history = await _chunked(
        session,
        lambda c: select(DealStageHistory)
        .where(DealStageHistory.deal_bitrix_id.in_(c))
        .order_by(DealStageHistory.created_time, DealStageHistory.bitrix_id),
        bids,
    )
    entered: dict[tuple[int, str], datetime] = {}
    for h in history:
        # Later rows overwrite earlier ones: the last time the deal entered that stage
        entered[(h.deal_bitrix_id, h.stage_bitrix_id)] = _as_utc(h.created_time)

    activities = await _chunked(
        session,
        lambda c: select(CrmActivity).where(CrmActivity.owner_type_id == 2, CrmActivity.owner_id.in_(c)),
        bids,
    )
    last_act: dict[int, tuple[datetime, CrmActivity]] = {}
    for a in activities:
        # Something that happened: created or completed, never a moment in the future
        stamps = [t for t in (_as_utc(a.created), _as_utc(a.completed_at)) if t and t <= now]
        ts = max(stamps) if stamps else None
        if ts and (a.owner_id not in last_act or ts > last_act[a.owner_id][0]):
            last_act[a.owner_id] = (ts, a)

    items: list[dict[str, Any]] = []
    by_stage: dict[str, dict[str, Any]] = {}
    by_manager: dict[int, dict[str, Any]] = {}
    for d in deals:
        stage = d.stage
        rule = rules.get(stage.bitrix_id) if stage else None
        if rule is None:
            continue
        key = (d.bitrix_id, stage.bitrix_id)
        if key in entered:
            since, since_source = entered[key], "bitrix"
        elif d.stage_changed_observed_at:
            since, since_source = _as_utc(d.stage_changed_observed_at), "observed"
        else:
            since, since_source = _as_utc(d.date_create) or now, "created"
        in_stage = rule.elapsed(cal, since, now)
        limit = rule.limit_seconds(cal)
        stuck = limit is not None and in_stage > limit
        act = last_act.get(d.bitrix_id)
        movement = max([t for t in (since, act[0] if act else None) if t])

        bucket = by_stage.setdefault(
            stage.bitrix_id,
            {"stage_id": stage.bitrix_id, "name": stage.name, "pipeline": rule.pipeline_name,
             "category_id": rule.category_id, "sort": rule.sort, "rule": rule.label(), "tracked": rule.tracked,
             "open": 0, "stuck": 0},
        )
        bucket["open"] += 1
        bucket["stuck"] += stuck
        if d.assigned_by_id:
            mb = by_manager.setdefault(
                d.assigned_by_id, {"manager_id": d.assigned_by_id, "name": _manager_name(d.assigned_manager), "open": 0, "stuck": 0}
            )
            mb["open"] += 1
            mb["stuck"] += stuck

        if only_stuck and not stuck:
            continue
        items.append(
            {
                "deal_id": d.id,
                "bitrix_id": d.bitrix_id,
                "title": d.title,
                "opportunity": float(d.opportunity) if d.opportunity is not None else None,
                "manager_id": d.assigned_by_id,
                "manager": _manager_name(d.assigned_manager),
                "stage_id": stage.bitrix_id,
                "stage": stage.name,
                "pipeline": rule.pipeline_name,
                "rule": rule.label(),
                "unit": rule.unit,
                "in_stage_seconds": round(in_stage),
                "limit_seconds": round(limit) if limit is not None else None,
                "over_seconds": round(in_stage - limit) if stuck else 0,
                "over_ratio": round(in_stage / limit, 2) if limit else None,
                "stuck": stuck,
                "in_stage_since": since.isoformat(),
                "in_stage_since_source": since_source,
                "last_movement_at": movement.isoformat(),
                "last_activity": (
                    {
                        "type": activity_type_label(act[1].type_id),
                        "subject": act[1].subject,
                        "at": act[0].isoformat(),
                        "completed": act[1].completed,
                    }
                    if act
                    else None
                ),
                "has_future_activity": d.has_future_activity,
                "next_deadline_at": _as_utc(d.next_deadline_at).isoformat() if d.next_deadline_at else None,
                "bitrix_url": deal_url(d.bitrix_id),
            }
        )
    items.sort(key=lambda i: (not i["stuck"], -(i["over_ratio"] or 0)))
    for m in by_manager.values():
        m["share"] = round(m["stuck"] / m["open"] * 100, 1) if m["open"] else None
    return {
        "items": items,
        "total": len(items),
        "stuck_total": sum(s["stuck"] for s in by_stage.values()),
        "open_total": sum(s["open"] for s in by_stage.values()),
        "by_stage": sorted(by_stage.values(), key=lambda s: (s["category_id"], s["sort"])),
        "by_manager": sorted(by_manager.values(), key=lambda m: (-m["stuck"], -(m["share"] or 0))),
        "work_calendar": {
            "hours": f"{cal.start:%H:%M}–{cal.end:%H:%M}",
            "workdays": sorted(cal.workdays),
        },
        "computed_at": now.isoformat(),
    }


def _stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"median_seconds": None, "avg_seconds": None, "count": 0}
    return {
        "median_seconds": round(statistics.median(values)),
        "avg_seconds": round(statistics.fmean(values)),
        "count": len(values),
    }


async def reaction_stats(
    session: AsyncSession,
    *,
    period_start: date,
    period_end: date,
    category_id: int | None = None,
    manager_id: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Working time from deal creation to «взят в работу» and to first contact.

    "First contact" = the deal left every reaction stage (Новая заявка, Взят в работу).
    Norms are the stage deadlines of those stages, summed for first contact.
    """
    now = now or utc_now()
    cal = get_work_calendar()
    rules = await load_rules(session)
    start_utc, _ = local_day_bounds(period_start)
    _, end_utc = local_day_bounds(period_end)

    filters = [
        CrmDeal.missing_from_bitrix.is_(False),
        CrmDeal.date_create >= start_utc,
        CrmDeal.date_create <= end_utc,
    ]
    if category_id is not None:
        filters.append(CrmDeal.category_id == category_id)
    if manager_id is not None:
        filters.append(CrmDeal.assigned_by_id == manager_id)
    deals = (
        await session.execute(select(CrmDeal).where(*filters).options(selectinload(CrmDeal.assigned_manager)))
    ).scalars().all()
    all_stages = (await session.execute(select(CrmStage))).scalars().all()
    stage_by_pk = {s.id: s for s in all_stages}
    paths = await _build_paths(session, list(deals), stage_by_pk)

    # Per pipeline: reaction stages ordered by sort; the first one is «Новая заявка»
    reaction_by_cat: dict[int, list[Rule]] = {}
    for r in rules.values():
        if r.reaction_stage:
            reaction_by_cat.setdefault(r.category_id, []).append(r)
    for lst in reaction_by_cat.values():
        lst.sort(key=lambda r: r.sort)

    rows: list[dict[str, Any]] = []
    for item in paths:
        d = item.deal
        stages = reaction_by_cat.get(d.category_id or -1)
        created = _as_utc(d.date_create)
        if not stages or created is None:
            continue
        reaction_ids = {r.stage_bitrix_id for r in stages}
        first_id = stages[0].stage_bitrix_id
        take_norm = stages[0].limit_seconds(cal)
        contact_norm = sum(r.limit_seconds(cal) or 0 for r in stages) or None
        after = [(t, s) for t, s in item.path if t >= created]
        has_history = item.source in ("bitrix", "observed")
        take_at = next((t for t, s in after if s != first_id), None)
        contact_at = next((t for t, s in after if s not in reaction_ids), None)
        current = stage_by_pk.get(d.stage_id) if d.stage_id else None
        waiting = bool(current and current.bitrix_id in reaction_ids and not d.closed)
        if not has_history and not waiting:
            # Only the current stage is known: we know it moved on, not when
            continue
        take = cal.work_seconds(created, take_at) if take_at else None
        contact = cal.work_seconds(created, contact_at) if contact_at else None
        waiting_for = cal.work_seconds(created, now) if waiting and contact is None else None
        late = (contact if contact is not None else waiting_for or 0) > contact_norm if contact_norm else False
        rows.append(
            {
                "deal_id": d.id,
                "bitrix_id": d.bitrix_id,
                "title": d.title,
                "manager_id": d.assigned_by_id,
                "manager": _manager_name(d.assigned_manager),
                "created_at": created.isoformat(),
                "take_seconds": round(take) if take is not None else None,
                "contact_seconds": round(contact) if contact is not None else None,
                "waiting_seconds": round(waiting_for) if waiting_for is not None else None,
                "take_norm_seconds": round(take_norm) if take_norm else None,
                "contact_norm_seconds": round(contact_norm) if contact_norm else None,
                "late": late,
                "stage": current.name if current else None,
                "bitrix_url": deal_url(d.bitrix_id),
            }
        )

    def summarize(group: list[dict[str, Any]]) -> dict[str, Any]:
        contacts = [r["contact_seconds"] for r in group if r["contact_seconds"] is not None]
        decided = [r for r in group if r["contact_seconds"] is not None or r["waiting_seconds"] is not None]
        return {
            "deals": len(group),
            "take": _stats([r["take_seconds"] for r in group if r["take_seconds"] is not None]),
            "contact": _stats(contacts),
            "late": sum(r["late"] for r in group),
            "late_share": round(sum(r["late"] for r in decided) / len(decided) * 100, 1) if decided else None,
            "waiting": sum(r["waiting_seconds"] is not None for r in group),
            "waiting_late": sum(r["waiting_seconds"] is not None and r["late"] for r in group),
        }

    managers: list[dict[str, Any]] = []
    if manager_id is None:
        by_m: dict[int, list[dict[str, Any]]] = {}
        for r in rows:
            if r["manager_id"]:
                by_m.setdefault(r["manager_id"], []).append(r)
        for mid, group in by_m.items():
            managers.append({"manager_id": mid, "name": group[0]["manager"], **summarize(group)})
        managers.sort(key=lambda m: -(m["contact"]["median_seconds"] or 0))

    worst = sorted(
        rows, key=lambda r: -(r["contact_seconds"] if r["contact_seconds"] is not None else r["waiting_seconds"] or 0)
    )[:20]
    norms = {
        cat: {
            "take": round(lst[0].limit_seconds(cal) or 0),
            "contact": round(sum(r.limit_seconds(cal) or 0 for r in lst)),
            "stages": [r.stage_name for r in lst],
        }
        for cat, lst in reaction_by_cat.items()
    }
    shown = reaction_by_cat.get(category_id) if category_id is not None else next(iter(reaction_by_cat.values()), None)
    names = [r.stage_name for r in shown] if shown else ["Новая заявка", "Взят в работу"]
    stage_list = ", ".join(f"«{n}»" for n in names)
    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "summary": summarize(rows),
        "managers": managers,
        "worst": worst,
        "norms": norms,
        "skipped_without_history": len(paths) - len(rows),
        "definitions": {
            "take": f"От создания сделки до перевода из первой стадии («{names[0]}») — в рабочем времени.",
            "contact": f"От создания до выхода из стадий реакции ({stage_list}) — в рабочем времени.",
            "late": "Дольше нормы: сумма сроков стадий реакции. Ждущие сейчас считаются, если уже вышли за норму.",
        },
        "computed_at": now.isoformat(),
    }


def validate_rule_input(threshold: float | Decimal | None, unit: str) -> None:
    if unit not in UNITS:
        raise ValueError(f"unit must be one of {UNITS}")
    if threshold is not None and not (0 < float(threshold) <= 1000):
        raise ValueError("threshold must be between 0 and 1000")

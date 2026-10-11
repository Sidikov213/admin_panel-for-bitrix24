"""Batch rule evaluation — non-blocking relative to Bitrix sync."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.timezone import utc_now
from app.models.crm import CrmActivity, CrmDeal, DealSnapshot
from app.models.sales_rules import (
    SalesRule,
    SalesRuleViolation,
    ViolationStatus,
    ViolationType,
)
from app.services.sales_rules.priority import pick_rules_by_check, rule_matches_deal

logger = logging.getLogger(__name__)

# Standard CrmDeal attribute mapping for required_fields (Bitrix field → column)
DEAL_COLUMN_MAP: dict[str, str] = {
    "TITLE": "title",
    "OPPORTUNITY": "opportunity",
    "CURRENCY_ID": "currency_id",
    "ASSIGNED_BY_ID": "assigned_by_id",
    "STAGE_ID": "stage_id",
    "CATEGORY_ID": "category_id",
    "CLOSEDATE": "closedate",
}


@dataclass(frozen=True)
class DetectedViolation:
    deal_id: int
    rule_id: int
    violation_type: str
    severity: str
    details: str
    current_value: str | None
    threshold: str | None
    manager_id: int | None
    opportunity: str | None


def _as_utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        from datetime import timezone

        return ts.replace(tzinfo=timezone.utc)
    return ts


def _field_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


async def load_enabled_rules(session: AsyncSession) -> list[SalesRule]:
    return list(
        (await session.execute(select(SalesRule).where(SalesRule.enabled.is_(True)))).scalars().all()
    )


async def _preload_overdue_owners(session: AsyncSession, now: datetime) -> set[int]:
    rows = (
        await session.execute(
            select(CrmActivity.owner_id)
            .where(
                CrmActivity.completed.is_(False),
                CrmActivity.deadline.isnot(None),
                CrmActivity.deadline < now,
                CrmActivity.owner_id.isnot(None),
            )
            .distinct()
        )
    ).all()
    return {int(r[0]) for r in rows if r[0] is not None}


async def _preload_latest_snapshots(
    session: AsyncSession, deal_ids: list[int]
) -> dict[int, dict]:
    if not deal_ids:
        return {}
    # Latest snapshot per deal via DISTINCT ON
    stmt = (
        select(DealSnapshot.deal_id, DealSnapshot.payload)
        .where(DealSnapshot.deal_id.in_(deal_ids))
        .order_by(DealSnapshot.deal_id, DealSnapshot.observed_at.desc())
        .distinct(DealSnapshot.deal_id)
    )
    rows = (await session.execute(stmt)).all()
    return {int(did): (payload or {}) for did, payload in rows}


def evaluate_deal(
    deal: CrmDeal,
    *,
    now: datetime,
    overdue_owners: set[int],
    snapshot: dict | None,
    rules: list[SalesRule],
) -> list[DetectedViolation]:
    matching = [
        r
        for r in rules
        if rule_matches_deal(r, category_id=deal.category_id, stage_id=deal.stage_id)
    ]
    if not matching:
        return []

    by_check = pick_rules_by_check(matching)
    out: list[DetectedViolation] = []
    opp = str(deal.opportunity) if deal.opportunity is not None else None

    def add(rule: SalesRule, vtype: ViolationType, details: str, current: str | None, threshold: str | None) -> None:
        out.append(
            DetectedViolation(
                deal_id=deal.id,
                rule_id=rule.id,
                violation_type=vtype.value,
                severity=rule.severity,
                details=details,
                current_value=current,
                threshold=threshold,
                manager_id=deal.assigned_by_id,
                opportunity=opp,
            )
        )

    # NO_FUTURE
    rule = by_check.get("future_activity_required")
    if rule and not deal.has_future_activity:
        add(rule, ViolationType.NO_FUTURE_ACTIVITY, "Нет следующего запланированного дела", "false", "future_activity_required=true")

    # OVERDUE
    rule = by_check.get("overdue_activity_allowed")
    if rule and deal.bitrix_id in overdue_owners:
        add(rule, ViolationType.OVERDUE_ACTIVITY, "Есть просроченное незавершённое дело", "overdue", "overdue_activity_allowed=false")

    # IDLE
    rule = by_check.get("max_idle_minutes")
    if rule and rule.max_idle_minutes:
        ref = _as_utc(deal.last_observed_activity_at) or _as_utc(deal.date_modify) or _as_utc(deal.observed_at)
        if ref is not None:
            idle_m = int((now - ref).total_seconds() // 60)
            if idle_m > rule.max_idle_minutes:
                add(
                    rule,
                    ViolationType.IDLE_TOO_LONG,
                    f"Нет наблюдаемого движения {idle_m} мин",
                    str(idle_m),
                    str(rule.max_idle_minutes),
                )

    # STAGE DURATION
    rule = by_check.get("max_stage_duration_minutes")
    if rule and rule.max_stage_duration_minutes:
        stage_ts = _as_utc(deal.stage_changed_observed_at) or _as_utc(deal.date_modify) or _as_utc(deal.date_create)
        if stage_ts is not None:
            stage_m = int((now - stage_ts).total_seconds() // 60)
            if stage_m > rule.max_stage_duration_minutes:
                add(
                    rule,
                    ViolationType.STAGE_TOO_LONG,
                    f"На этапе {stage_m} мин (наблюдаемо)",
                    str(stage_m),
                    str(rule.max_stage_duration_minutes),
                )

    # NEXT ACTIVITY TOO FAR
    rule = by_check.get("max_next_activity_minutes")
    if rule and rule.max_next_activity_minutes and deal.next_deadline_at:
        nd = _as_utc(deal.next_deadline_at)
        if nd and nd > now:
            ahead_m = int((nd - now).total_seconds() // 60)
            if ahead_m > rule.max_next_activity_minutes:
                add(
                    rule,
                    ViolationType.NEXT_ACTIVITY_TOO_FAR,
                    f"Следующее дело через {ahead_m} мин",
                    str(ahead_m),
                    str(rule.max_next_activity_minutes),
                )

    # REQUIRED FIELDS
    rule = by_check.get("required_fields")
    if rule and rule.required_fields:
        payload = snapshot or {}
        missing: list[str] = []
        for fname in rule.required_fields:
            col = DEAL_COLUMN_MAP.get(fname)
            if col is not None:
                val = getattr(deal, col, None)
            else:
                val = payload.get(fname)
            if _field_empty(val):
                missing.append(fname)
        if missing:
            add(
                rule,
                ViolationType.REQUIRED_FIELD_MISSING,
                f"Не заполнены поля: {', '.join(missing)}",
                ",".join(missing),
                ",".join(rule.required_fields),
            )

    # COMMENT rules — unsupported capability (never emit violations)
    # required_comment / comment_max_age intentionally no-op until timeline sync exists.

    return out


async def detect_all(
    session: AsyncSession,
    *,
    rules: list[SalesRule] | None = None,
    now: datetime | None = None,
) -> list[DetectedViolation]:
    now = now or utc_now()
    rules = rules if rules is not None else await load_enabled_rules(session)
    if not rules:
        return []

    deals = list(
        (
            await session.execute(
                select(CrmDeal).where(
                    CrmDeal.closed.is_(False),
                    CrmDeal.missing_from_bitrix.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )
    overdue_owners = await _preload_overdue_owners(session, now)
    snapshots = await _preload_latest_snapshots(session, [d.id for d in deals])

    detected: list[DetectedViolation] = []
    for d in deals:
        detected.extend(
            evaluate_deal(
                d,
                now=now,
                overdue_owners=overdue_owners,
                snapshot=snapshots.get(d.id),
                rules=rules,
            )
        )
    return detected


async def apply_detections(
    session: AsyncSession,
    detected: list[DetectedViolation],
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """
    Occurrence model:
    - At most one OPEN per (deal_id, rule_id, violation_type) via open_map.
    - Condition clears → RESOLVED + resolved_at.
    - Condition returns → NEW open occurrence (history preserved; Postgres partial unique
      enforces single OPEN; SQLite relies on this map).
    """
    now = now or utc_now()
    open_rows = list(
        (
            await session.execute(
                select(SalesRuleViolation).where(SalesRuleViolation.status == ViolationStatus.open.value)
            )
        )
        .scalars()
        .all()
    )
    open_map = {(v.deal_id, v.rule_id, v.violation_type): v for v in open_rows}
    detected_keys = {(d.deal_id, d.rule_id, d.violation_type) for d in detected}

    created = 0
    resolved = 0
    kept = 0
    reopened = 0

    for key, row in open_map.items():
        if key not in detected_keys:
            row.status = ViolationStatus.resolved.value
            row.resolved_at = now
            resolved += 1
        else:
            kept += 1

    for d in detected:
        key = (d.deal_id, d.rule_id, d.violation_type)
        if key in open_map:
            row = open_map[key]
            row.details = d.details
            row.current_value = d.current_value
            row.threshold = d.threshold
            row.severity = d.severity
            row.manager_id = d.manager_id
            row.opportunity = d.opportunity
            continue
        session.add(
            SalesRuleViolation(
                deal_id=d.deal_id,
                rule_id=d.rule_id,
                violation_type=d.violation_type,
                severity=d.severity,
                status=ViolationStatus.open.value,
                detected_at=now,
                details=d.details,
                current_value=d.current_value,
                threshold=d.threshold,
                manager_id=d.manager_id,
                opportunity=d.opportunity,
            )
        )
        created += 1

    await session.flush()
    return {
        "created": created,
        "resolved": resolved,
        "kept": kept,
        "reopened_as_new": reopened,
        "detected": len(detected),
    }


async def run_evaluation(session: AsyncSession) -> dict[str, Any]:
    t0 = utc_now()
    rules = await load_enabled_rules(session)
    detected = await detect_all(session, rules=rules, now=t0)
    stats = await apply_detections(session, detected, now=t0)
    elapsed_ms = int((utc_now() - t0).total_seconds() * 1000)
    result = {
        "ok": True,
        "enabled_rules": len(rules),
        "elapsed_ms": elapsed_ms,
        **stats,
        "evaluated_at": t0.isoformat(),
    }
    logger.info("sales_rules_evaluation %s", result)
    return result


async def run_evaluation_safe() -> dict[str, Any]:
    """Own session; never raises to caller (sync must stay successful)."""
    from app.db.session import async_session_factory

    try:
        async with async_session_factory() as session:
            result = await run_evaluation(session)
            await session.commit()
            return result
    except Exception as exc:
        logger.exception("sales_rules_evaluation_failed")
        return {"ok": False, "error": str(exc)}


async def preview_rule_impact(
    session: AsyncSession,
    rule_payload: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Ephemeral evaluation of one (possibly unsaved) rule — does not write violations."""
    now = now or utc_now()
    # Build ephemeral SalesRule instance (not added to session)
    ephemeral = SalesRule(
        id=rule_payload.get("id") or -1,
        rule_name=rule_payload.get("rule_name") or "preview",
        description=rule_payload.get("description"),
        pipeline_bitrix_id=rule_payload.get("pipeline_bitrix_id"),
        stage_id=rule_payload.get("stage_id"),
        enabled=True,  # preview as if enabled
        max_idle_minutes=rule_payload.get("max_idle_minutes"),
        future_activity_required=rule_payload.get("future_activity_required"),
        max_next_activity_minutes=rule_payload.get("max_next_activity_minutes"),
        overdue_activity_allowed=rule_payload.get("overdue_activity_allowed"),
        required_fields=rule_payload.get("required_fields"),
        required_comment=rule_payload.get("required_comment"),
        comment_max_age_minutes=rule_payload.get("comment_max_age_minutes"),
        max_stage_duration_minutes=rule_payload.get("max_stage_duration_minutes"),
        severity=rule_payload.get("severity") or "medium",
    )
    deals = list(
        (
            await session.execute(
                select(CrmDeal)
                .where(CrmDeal.closed.is_(False), CrmDeal.missing_from_bitrix.is_(False))
                .options(selectinload(CrmDeal.assigned_manager))
            )
        )
        .scalars()
        .all()
    )
    overdue_owners = await _preload_overdue_owners(session, now)
    need_snap = bool(ephemeral.required_fields)
    snapshots = await _preload_latest_snapshots(session, [d.id for d in deals]) if need_snap else {}

    affected: list[CrmDeal] = []
    by_manager: dict[int | None, dict[str, Any]] = {}
    for d in deals:
        hits = evaluate_deal(
            d,
            now=now,
            overdue_owners=overdue_owners,
            snapshot=snapshots.get(d.id),
            rules=[ephemeral],
        )
        if not hits:
            continue
        affected.append(d)
        mid = d.assigned_by_id
        bucket = by_manager.setdefault(
            mid,
            {
                "manager_id": mid,
                "manager_name": (
                    f"{d.assigned_manager.name} {d.assigned_manager.last_name}".strip()
                    if d.assigned_manager
                    else "Без менеджера"
                ),
                "deals_count": 0,
                "amount": 0.0,
            },
        )
        bucket["deals_count"] += 1
        bucket["amount"] += float(d.opportunity or 0)

    amount = float(sum((d.opportunity or Decimal("0")) for d in affected))
    return {
        "deals_affected": len(affected),
        "amount_affected": amount,
        "by_manager": sorted(by_manager.values(), key=lambda x: -x["deals_count"]),
        "sample_deal_ids": [d.id for d in affected[:20]],
        "persisted": False,
        "note": "Preview only — violations are not saved.",
    }

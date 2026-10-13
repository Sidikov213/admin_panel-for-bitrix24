"""Pure schedule/day-plan/violation logic for Manager Control V3 (no I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

# Violation types (no IDLE / OFFLINE — Time Control disabled)
WORKDAY_NOT_STARTED = "WORKDAY_NOT_STARTED"
LATE_START = "LATE_START"
WORKDAY_NOT_CLOSED = "WORKDAY_NOT_CLOSED"
EARLY_FINISH = "EARLY_FINISH"
SHORT_WORKDAY = "SHORT_WORKDAY"
BREAK_LIMIT_EXCEEDED = "BREAK_LIMIT_EXCEEDED"
STALE_UNCLOSED_DAY = "STALE_UNCLOSED_DAY"

ALL_VIOLATION_TYPES = (
    WORKDAY_NOT_STARTED,
    LATE_START,
    WORKDAY_NOT_CLOSED,
    EARLY_FINISH,
    SHORT_WORKDAY,
    BREAK_LIMIT_EXCEEDED,
    STALE_UNCLOSED_DAY,
)

STATE_OPEN = "OPEN"
STATE_RESOLVED = "RESOLVED"

SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_HIGH = "HIGH"

NON_WORKING_KINDS = frozenset({"weekend", "holiday", "day_off", "absence", "vacation", "sick"})


@dataclass(frozen=True)
class ScheduleSpec:
    id: int
    name: str
    timezone: str
    weekdays: list[int]  # 1=Mon .. 7=Sun
    start_time: str
    end_time: str
    required_minutes: int | None
    late_grace_minutes: int | None
    early_finish_grace_minutes: int | None
    max_break_minutes: int | None
    not_started_threshold_minutes: int | None
    not_closed_grace_minutes: int | None
    enabled: bool


@dataclass(frozen=True)
class DayPlan:
    """Effective plan for one manager on one date. None schedule → no DayPlan."""

    schedule_id: int
    schedule_name: str
    timezone: str
    is_working: bool
    non_working_reason: str | None
    start_hm: str | None
    end_hm: str | None
    required_minutes: int | None
    late_grace_minutes: int
    early_finish_grace_minutes: int
    max_break_minutes: int | None
    not_started_threshold_minutes: int
    not_closed_grace_minutes: int
    kind: str  # working | shortened | weekend | …


@dataclass(frozen=True)
class WorkdayFacts:
    status_normalized: str | None
    time_start: datetime | None
    time_finish: datetime | None
    duration_seconds: int | None
    time_leaks_seconds: int | None
    is_stale_unclosed: bool


@dataclass(frozen=True)
class ViolationCandidate:
    violation_type: str
    threshold_value: str | None
    actual_value: str | None
    details: dict[str, Any]


def parse_hm(value: str) -> time:
    parts = value.strip().split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    return time(hour=h, minute=m)


def combine_local(day: date, hm: str, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    return datetime.combine(day, parse_hm(hm), tzinfo=tz)


def iso_weekday(d: date) -> int:
    return d.isoweekday()  # 1=Mon .. 7=Sun


def build_day_plan(
    schedule: ScheduleSpec | None,
    *,
    day: date,
    global_override: dict[str, Any] | None = None,
    manager_override: dict[str, Any] | None = None,
    absence_kind: str | None = None,
) -> DayPlan | None:
    """Resolve effective day plan. No schedule → None (no violations)."""
    if schedule is None or not schedule.enabled:
        return None

    override = manager_override or global_override
    if absence_kind:
        return DayPlan(
            schedule_id=schedule.id,
            schedule_name=schedule.name,
            timezone=schedule.timezone,
            is_working=False,
            non_working_reason=absence_kind,
            start_hm=None,
            end_hm=None,
            required_minutes=None,
            late_grace_minutes=schedule.late_grace_minutes or 0,
            early_finish_grace_minutes=schedule.early_finish_grace_minutes or 0,
            max_break_minutes=schedule.max_break_minutes,
            not_started_threshold_minutes=schedule.not_started_threshold_minutes or 0,
            not_closed_grace_minutes=schedule.not_closed_grace_minutes or 0,
            kind=absence_kind,
        )

    if override:
        kind = str(override.get("kind") or "working")
        if kind in NON_WORKING_KINDS:
            return DayPlan(
                schedule_id=schedule.id,
                schedule_name=schedule.name,
                timezone=schedule.timezone,
                is_working=False,
                non_working_reason=kind,
                start_hm=None,
                end_hm=None,
                required_minutes=None,
                late_grace_minutes=schedule.late_grace_minutes or 0,
                early_finish_grace_minutes=schedule.early_finish_grace_minutes or 0,
                max_break_minutes=schedule.max_break_minutes,
                not_started_threshold_minutes=schedule.not_started_threshold_minutes or 0,
                not_closed_grace_minutes=schedule.not_closed_grace_minutes or 0,
                kind=kind,
            )
        start_hm = override.get("start_time") or schedule.start_time
        end_hm = override.get("end_time") or schedule.end_time
        req = override.get("required_minutes")
        if req is None:
            req = schedule.required_minutes
        return DayPlan(
            schedule_id=schedule.id,
            schedule_name=schedule.name,
            timezone=schedule.timezone,
            is_working=True,
            non_working_reason=None,
            start_hm=str(start_hm),
            end_hm=str(end_hm),
            required_minutes=int(req) if req is not None else None,
            late_grace_minutes=schedule.late_grace_minutes or 0,
            early_finish_grace_minutes=schedule.early_finish_grace_minutes or 0,
            max_break_minutes=schedule.max_break_minutes,
            not_started_threshold_minutes=schedule.not_started_threshold_minutes or 0,
            not_closed_grace_minutes=schedule.not_closed_grace_minutes or 0,
            kind=kind if kind else "working",
        )

    if iso_weekday(day) not in (schedule.weekdays or []):
        return DayPlan(
            schedule_id=schedule.id,
            schedule_name=schedule.name,
            timezone=schedule.timezone,
            is_working=False,
            non_working_reason="weekend",
            start_hm=None,
            end_hm=None,
            required_minutes=None,
            late_grace_minutes=schedule.late_grace_minutes or 0,
            early_finish_grace_minutes=schedule.early_finish_grace_minutes or 0,
            max_break_minutes=schedule.max_break_minutes,
            not_started_threshold_minutes=schedule.not_started_threshold_minutes or 0,
            not_closed_grace_minutes=schedule.not_closed_grace_minutes or 0,
            kind="weekend",
        )

    return DayPlan(
        schedule_id=schedule.id,
        schedule_name=schedule.name,
        timezone=schedule.timezone,
        is_working=True,
        non_working_reason=None,
        start_hm=schedule.start_time,
        end_hm=schedule.end_time,
        required_minutes=schedule.required_minutes,
        late_grace_minutes=schedule.late_grace_minutes or 0,
        early_finish_grace_minutes=schedule.early_finish_grace_minutes or 0,
        max_break_minutes=schedule.max_break_minutes,
        not_started_threshold_minutes=schedule.not_started_threshold_minutes or 0,
        not_closed_grace_minutes=schedule.not_closed_grace_minutes or 0,
        kind="working",
    )


def evaluate_day_violations(
    plan: DayPlan | None,
    facts: WorkdayFacts,
    *,
    day: date,
    now: datetime,
) -> list[ViolationCandidate]:
    """Compute active violation candidates. Empty when no schedule / non-working / too early."""
    out: list[ViolationCandidate] = []

    # STALE can surface even without schedule (existing Timeman semantics)
    if facts.is_stale_unclosed:
        out.append(
            ViolationCandidate(
                violation_type=STALE_UNCLOSED_DAY,
                threshold_value=None,
                actual_value=facts.status_normalized,
                details={"source": "timeman_stale_expired"},
            )
        )

    if plan is None or not plan.is_working or not plan.start_hm or not plan.end_hm:
        return out

    tz = ZoneInfo(plan.timezone)
    now_local = now.astimezone(tz)
    # Never evaluate future work dates
    if day > now_local.date():
        return out

    scheduled_start = combine_local(day, plan.start_hm, plan.timezone)
    scheduled_end = combine_local(day, plan.end_hm, plan.timezone)
    late_deadline = scheduled_start + timedelta(minutes=plan.late_grace_minutes)
    not_started_after = scheduled_start + timedelta(minutes=plan.not_started_threshold_minutes)
    not_closed_after = scheduled_end + timedelta(minutes=plan.not_closed_grace_minutes)
    early_ok_until = scheduled_end - timedelta(minutes=plan.early_finish_grace_minutes)

    start = facts.time_start.astimezone(tz) if facts.time_start else None
    finish = facts.time_finish.astimezone(tz) if facts.time_finish else None

    # LATE_START — only after grace window, and only with an actual late start
    if now_local >= late_deadline and start is not None and start > late_deadline:
        mins = int((start - scheduled_start).total_seconds() // 60)
        out.append(
            ViolationCandidate(
                violation_type=LATE_START,
                threshold_value=late_deadline.strftime("%H:%M"),
                actual_value=start.strftime("%H:%M"),
                details={"late_minutes": mins, "grace_minutes": plan.late_grace_minutes},
            )
        )

    # WORKDAY_NOT_STARTED — after threshold, no start yet (not for closed/stale with start)
    if (
        now_local >= not_started_after
        and start is None
        and not facts.is_stale_unclosed
        and facts.status_normalized not in {"closed", "completed"}
    ):
        out.append(
            ViolationCandidate(
                violation_type=WORKDAY_NOT_STARTED,
                threshold_value=not_started_after.strftime("%H:%M"),
                actual_value=None,
                details={"threshold_minutes": plan.not_started_threshold_minutes},
            )
        )

    # EARLY_FINISH — finished before allowed early window
    if finish is not None and finish < early_ok_until:
        # Only after the early window has meaning (day progressed past finish or they closed)
        if now_local >= finish:
            mins = int((scheduled_end - finish).total_seconds() // 60)
            out.append(
                ViolationCandidate(
                    violation_type=EARLY_FINISH,
                    threshold_value=early_ok_until.strftime("%H:%M"),
                    actual_value=finish.strftime("%H:%M"),
                    details={"early_minutes": mins},
                )
            )

    # WORKDAY_NOT_CLOSED — after end+grace, no finish
    if now_local >= not_closed_after and finish is None and start is not None:
        out.append(
            ViolationCandidate(
                violation_type=WORKDAY_NOT_CLOSED,
                threshold_value=not_closed_after.strftime("%H:%M"),
                actual_value=None,
                details={"grace_minutes": plan.not_closed_grace_minutes},
            )
        )

    # SHORT_WORKDAY — closed (or day ended) with duration under required
    if plan.required_minutes is not None and facts.duration_seconds is not None:
        required_sec = plan.required_minutes * 60
        day_ended = now_local >= not_closed_after or finish is not None
        if day_ended and facts.duration_seconds < required_sec:
            out.append(
                ViolationCandidate(
                    violation_type=SHORT_WORKDAY,
                    threshold_value=str(plan.required_minutes),
                    actual_value=str(facts.duration_seconds // 60),
                    details={
                        "required_minutes": plan.required_minutes,
                        "actual_minutes": facts.duration_seconds // 60,
                    },
                )
            )

    # BREAK_LIMIT_EXCEEDED
    if plan.max_break_minutes is not None and facts.time_leaks_seconds is not None:
        max_sec = plan.max_break_minutes * 60
        if facts.time_leaks_seconds > max_sec and (finish is not None or now_local >= not_closed_after):
            out.append(
                ViolationCandidate(
                    violation_type=BREAK_LIMIT_EXCEEDED,
                    threshold_value=str(plan.max_break_minutes),
                    actual_value=str(facts.time_leaks_seconds // 60),
                    details={
                        "max_break_minutes": plan.max_break_minutes,
                        "actual_break_minutes": facts.time_leaks_seconds // 60,
                    },
                )
            )

    return out


def severity_for(violation_type: str, severity_by_type: dict[str, str] | None) -> str:
    if severity_by_type and violation_type in severity_by_type:
        val = str(severity_by_type[violation_type]).upper()
        if val in {SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_HIGH}:
            return val
    defaults = {
        WORKDAY_NOT_STARTED: SEVERITY_HIGH,
        LATE_START: SEVERITY_WARNING,
        WORKDAY_NOT_CLOSED: SEVERITY_HIGH,
        EARLY_FINISH: SEVERITY_WARNING,
        SHORT_WORKDAY: SEVERITY_WARNING,
        BREAK_LIMIT_EXCEEDED: SEVERITY_INFO,
        STALE_UNCLOSED_DAY: SEVERITY_WARNING,
    }
    return defaults.get(violation_type, SEVERITY_WARNING)


def is_enforcement_active(enforcement_start: date | None, day: date) -> bool:
    if enforcement_start is None:
        return False
    return day >= enforcement_start


def violation_label_ru(violation_type: str) -> str:
    return {
        WORKDAY_NOT_STARTED: "Не начал день",
        LATE_START: "Опоздание",
        WORKDAY_NOT_CLOSED: "Не завершил день",
        EARLY_FINISH: "Ранний уход",
        SHORT_WORKDAY: "Короткий день",
        BREAK_LIMIT_EXCEEDED: "Перерывы сверх лимита",
        STALE_UNCLOSED_DAY: "Незакрытый день (stale)",
    }.get(violation_type, violation_type)

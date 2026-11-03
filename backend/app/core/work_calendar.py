"""Working-time arithmetic for the sales team schedule.

A lead that arrives on Friday at 16:50 is not "64 hours late" on Monday morning: deadlines
measured in working hours only count time inside the working day, on working days,
outside the company-wide vacation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from app.core.config import get_settings

_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
# Longer spans are not walked day by day; nothing in the panel needs more precision
MAX_DAYS_WALKED = 800


def parse_weekdays(spec: str) -> frozenset[int]:
    days: set[int] = set()
    for part in spec.lower().replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = (_WEEKDAYS.index(x) for x in part.split("-", 1))
            days.update(range(a, b + 1) if a <= b else [*range(a, 7), *range(0, b + 1)])
        else:
            days.add(_WEEKDAYS.index(part))
    return frozenset(days)


def parse_hours(spec: str) -> tuple[time, time]:
    start, end = (time.fromisoformat(x.strip()) for x in spec.split("-", 1))
    if end <= start:
        raise ValueError("WORK_HOURS end must be after start")
    return start, end


def parse_holidays(spec: str) -> tuple[tuple[tuple[int, int], tuple[int, int]], ...]:
    ranges = []
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        a, _, b = part.partition("..")
        b = b or a
        ranges.append((tuple(int(x) for x in a.split("-")), tuple(int(x) for x in b.split("-"))))
    return tuple(ranges)  # type: ignore[return-value]


@dataclass(frozen=True)
class WorkCalendar:
    tz: ZoneInfo
    workdays: frozenset[int]
    start: time
    end: time
    holidays: tuple[tuple[tuple[int, int], tuple[int, int]], ...] = ()

    @property
    def day_seconds(self) -> float:
        return (datetime.combine(date.min, self.end) - datetime.combine(date.min, self.start)).total_seconds()

    def is_holiday(self, d: date) -> bool:
        md = (d.month, d.day)
        for a, b in self.holidays:
            if (a <= md <= b) if a <= b else (md >= a or md <= b):
                return True
        return False

    def is_workday(self, d: date) -> bool:
        return d.weekday() in self.workdays and not self.is_holiday(d)

    def work_seconds(self, a: datetime, b: datetime) -> float:
        """Working seconds inside [a, b] (both timezone-aware)."""
        if b <= a:
            return 0.0
        la, lb = a.astimezone(self.tz), b.astimezone(self.tz)
        total = 0.0
        d = la.date()
        last = lb.date()
        walked = 0
        while d <= last and walked < MAX_DAYS_WALKED:
            if self.is_workday(d):
                day_start = datetime.combine(d, self.start, tzinfo=self.tz)
                day_end = datetime.combine(d, self.end, tzinfo=self.tz)
                lo, hi = max(day_start, la), min(day_end, lb)
                if hi > lo:
                    total += (hi - lo).total_seconds()
            d += timedelta(days=1)
            walked += 1
        if d <= last:
            # Beyond the walk window: approximate with the average working share of a week
            remaining_days = (last - d).days + 1
            total += remaining_days * self.day_seconds * len(self.workdays) / 7
        return total

    def add_work_seconds(self, a: datetime, seconds: float) -> datetime:
        """Moment when `seconds` of working time have passed after `a` (deadline from start)."""
        la = a.astimezone(self.tz)
        d = la.date()
        left = seconds
        for _ in range(MAX_DAYS_WALKED):
            if self.is_workday(d):
                day_start = datetime.combine(d, self.start, tzinfo=self.tz)
                day_end = datetime.combine(d, self.end, tzinfo=self.tz)
                lo = max(day_start, la)
                if day_end > lo:
                    avail = (day_end - lo).total_seconds()
                    if left <= avail:
                        return (lo + timedelta(seconds=left)).astimezone(timezone.utc)
                    left -= avail
            d += timedelta(days=1)
        return (la + timedelta(seconds=seconds)).astimezone(timezone.utc)


@lru_cache
def get_work_calendar() -> WorkCalendar:
    s = get_settings()
    start, end = parse_hours(s.WORK_HOURS)
    return WorkCalendar(
        tz=ZoneInfo(s.APP_TIMEZONE),
        workdays=parse_weekdays(s.WORK_DAYS),
        start=start,
        end=end,
        holidays=parse_holidays(s.COMPANY_HOLIDAYS),
    )

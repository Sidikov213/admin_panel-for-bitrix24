"""Period presets and previous-period pairing (Europe/Moscow calendar)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from app.core.timezone import app_tz, utc_now

PeriodPreset = Literal[
    "today",
    "yesterday",
    "last_7_days",
    "current_week",
    "previous_week",
    "current_month",
    "previous_month",
    "custom",
]

PERIOD_PRESETS: tuple[PeriodPreset, ...] = (
    "today",
    "yesterday",
    "last_7_days",
    "current_week",
    "previous_week",
    "current_month",
    "previous_month",
    "custom",
)


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date
    preset: PeriodPreset

    def previous(self) -> DateRange:
        """Return a comparable previous range (same length or natural prior period)."""
        if self.preset == "today":
            d = self.start - timedelta(days=1)
            return DateRange(d, d, "yesterday")
        if self.preset == "yesterday":
            d = self.start - timedelta(days=1)
            return DateRange(d, d, "custom")
        if self.preset == "current_week":
            return resolve_preset("previous_week")
        if self.preset == "previous_week":
            # week before previous
            start = self.start - timedelta(days=7)
            end = self.end - timedelta(days=7)
            return DateRange(start, end, "custom")
        if self.preset == "current_month":
            return resolve_preset("previous_month")
        if self.preset == "previous_month":
            # month before previous
            first = self.start.replace(day=1)
            prev_last = first - timedelta(days=1)
            prev_first = prev_last.replace(day=1)
            return DateRange(prev_first, prev_last, "custom")
        # last_7_days / custom: same length immediately before
        length = (self.end - self.start).days + 1
        end = self.start - timedelta(days=1)
        start = end - timedelta(days=length - 1)
        return DateRange(start, end, "custom")


def today_local() -> date:
    return utc_now().astimezone(app_tz()).date()


def _week_bounds(d: date) -> tuple[date, date]:
    """Monday–Sunday week containing d."""
    start = d - timedelta(days=d.weekday())
    end = start + timedelta(days=6)
    return start, end


def resolve_preset(preset: PeriodPreset, *, custom_start: date | None = None, custom_end: date | None = None) -> DateRange:
    today = today_local()
    if preset == "today":
        return DateRange(today, today, preset)
    if preset == "yesterday":
        y = today - timedelta(days=1)
        return DateRange(y, y, preset)
    if preset == "last_7_days":
        return DateRange(today - timedelta(days=6), today, preset)
    if preset == "current_week":
        start, end = _week_bounds(today)
        return DateRange(start, min(end, today), preset)
    if preset == "previous_week":
        start, end = _week_bounds(today - timedelta(days=7))
        return DateRange(start, end, preset)
    if preset == "current_month":
        start = today.replace(day=1)
        return DateRange(start, today, preset)
    if preset == "previous_month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return DateRange(first_prev, last_prev, preset)
    # custom
    if custom_start is None or custom_end is None:
        return DateRange(today - timedelta(days=6), today, "custom")
    if custom_end < custom_start:
        custom_start, custom_end = custom_end, custom_start
    return DateRange(custom_start, custom_end, "custom")


def resolve_period(
    *,
    preset: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> DateRange:
    if preset and preset in PERIOD_PRESETS and preset != "custom":
        return resolve_preset(preset)  # type: ignore[arg-type]
    if period_start is not None and period_end is not None:
        return resolve_preset("custom", custom_start=period_start, custom_end=period_end)
    if preset == "custom" and period_start is not None and period_end is not None:
        return resolve_preset("custom", custom_start=period_start, custom_end=period_end)
    # default: last 7 days
    return resolve_preset("last_7_days")

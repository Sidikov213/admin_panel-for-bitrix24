"""Period comparison helpers — absolute and percent deltas."""

from __future__ import annotations

from typing import Any


COMPARISON_KEYS = (
    "new_deals_count",
    "won_count",
    "lost_count",
    "sum_won_opportunity",
    "overdue_activities_unique",
    "deals_without_future_activity_count",
    "active_deals_count",
    "sum_active_opportunity",
    "money_requiring_attention",
    "deals_requiring_attention_count",
)


def metric_delta(current: float | int, previous: float | int) -> dict[str, Any]:
    """Compare two scalar metrics. pct_delta is None when previous == 0 (avoid ∞%)."""
    cur = float(current)
    prev = float(previous)
    abs_delta = cur - prev
    if prev == 0:
        pct_delta = None
    else:
        pct_delta = round((abs_delta / prev) * 100.0, 1)
    return {
        "current": current if isinstance(current, int) and float(current).is_integer() else cur,
        "previous": previous if isinstance(previous, int) and float(previous).is_integer() else prev,
        "abs_delta": abs_delta if not (isinstance(current, int) and isinstance(previous, int)) else int(abs_delta),
        "pct_delta": pct_delta,
    }


def compare_kpi_dicts(current: dict[str, Any], previous: dict[str, Any], keys: tuple[str, ...] = COMPARISON_KEYS) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in keys:
        if key not in current and key not in previous:
            continue
        out[key] = metric_delta(current.get(key, 0) or 0, previous.get(key, 0) or 0)
    return out

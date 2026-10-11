from datetime import date, timedelta

from app.analytics.compare import metric_delta, compare_kpi_dicts
from app.analytics.periods import resolve_preset, resolve_period, today_local


def test_metric_delta_hides_infinite_percent() -> None:
    d = metric_delta(5, 0)
    assert d["abs_delta"] == 5
    assert d["pct_delta"] is None


def test_metric_delta_percent() -> None:
    d = metric_delta(12, 10)
    assert d["abs_delta"] == 2
    assert d["pct_delta"] == 20.0


def test_compare_kpi_dicts() -> None:
    cur = {"new_deals_count": 10, "won_count": 2}
    prev = {"new_deals_count": 5, "won_count": 0}
    out = compare_kpi_dicts(cur, prev)
    assert out["new_deals_count"]["pct_delta"] == 100.0
    assert out["won_count"]["pct_delta"] is None


def test_previous_week_pair() -> None:
    rng = resolve_preset("current_week")
    prev = rng.previous()
    assert prev.end < rng.start or prev.end <= rng.start
    assert (prev.end - prev.start).days == 6


def test_last_7_days_previous_same_length() -> None:
    rng = resolve_preset("last_7_days")
    prev = rng.previous()
    assert (rng.end - rng.start).days == (prev.end - prev.start).days


def test_resolve_period_custom() -> None:
    start = date(2026, 9, 1)
    end = date(2026, 9, 15)
    rng = resolve_period(period_start=start, period_end=end)
    assert rng.start == start
    assert rng.end == end
    assert rng.preset == "custom"


def test_today_local_is_date() -> None:
    assert isinstance(today_local(), date)

"""Data freshness signals for UI banners."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.timezone import utc_now

STALE_AFTER_MINUTES = 15


def _parse_ts(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, dict):
        return _parse_ts(value.get("at"))
    if isinstance(value, str) and value:
        try:
            s = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def build_freshness(
    *,
    last_successful_sync_at: datetime | str | dict | None,
    last_attempted_sync_at: datetime | str | dict | None = None,
    latest_run_status: str | None = None,
) -> dict[str, Any]:
    now = utc_now()
    last_ok = _parse_ts(last_successful_sync_at)
    last_attempt = _parse_ts(last_attempted_sync_at) or last_ok
    age_minutes: float | None = None
    if last_ok is not None:
        age_minutes = round((now - last_ok).total_seconds() / 60.0, 1)

    failed = latest_run_status == "failed"
    stale = failed or (age_minutes is not None and age_minutes > STALE_AFTER_MINUTES) or last_ok is None

    warning: str | None = None
    if failed:
        warning = "Последняя синхронизация завершилась с ошибкой"
    elif last_ok is None:
        warning = "Синхронизация ещё не выполнялась — данные могут быть неполными"
    elif age_minutes is not None and age_minutes > STALE_AFTER_MINUTES:
        warning = "Данные могут быть устаревшими"

    return {
        "last_updated_at": last_ok.isoformat() if last_ok else None,
        "last_attempted_at": last_attempt.isoformat() if last_attempt else None,
        "age_minutes": age_minutes,
        "stale_after_minutes": STALE_AFTER_MINUTES,
        "is_stale": stale,
        "sync_failed": failed,
        "warning": warning,
    }

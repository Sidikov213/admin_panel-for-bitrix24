"""Parse Bitrix timeman.status payloads into normalized local fields."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.core.timezone import app_tz, parse_bitrix_datetime

# Normalized statuses used in DB + API
STATUS_WORKING = "working"
STATUS_PAUSED = "paused"
STATUS_CLOSED = "closed"
STATUS_NOT_STARTED = "not_started"
STATUS_STALE_UNCLOSED = "stale_unclosed"
STATUS_UNKNOWN_BITRIX = "unknown_bitrix"
STATUS_NO_DATA = "no_data"
# Legacy alias kept for older rows
STATUS_UNKNOWN = STATUS_UNKNOWN_BITRIX

STATUS_LABELS_RU = {
    STATUS_WORKING: "Работает",
    STATUS_PAUSED: "Перерыв",
    STATUS_CLOSED: "Рабочий день завершён",
    STATUS_NOT_STARTED: "Не начал рабочий день",
    STATUS_STALE_UNCLOSED: "Незакрытый рабочий день",
    STATUS_UNKNOWN_BITRIX: "Неизвестный статус Bitrix",
    STATUS_NO_DATA: "Нет данных Timeman",
}

_MONTHS_RU = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

_HMS_RE = re.compile(r"^(\d+):(\d{2}):(\d{2})$")


def parse_hms_to_seconds(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return None
    s = value.strip()
    m = _HMS_RE.match(s)
    if not m:
        return None
    h, mi, sec = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return h * 3600 + mi * 60 + sec


def format_seconds(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    if seconds < 0:
        seconds = 0
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_date_ru(d: date) -> str:
    return f"{d.day} {_MONTHS_RU[d.month]} {d.year}"


def _local_date(dt: datetime | None, *, fallback: date) -> date | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(app_tz()).date()


def normalize_timeman_status(
    status_raw: str | None,
    *,
    time_start: datetime | None,
    time_finish: datetime | None = None,
    observed_at: datetime | None = None,
    today: date | None = None,
) -> str:
    """Map Bitrix STATUS to Focus labels. Stale EXPIRED ≠ working."""
    if today is None:
        from app.core.timezone import utc_now

        ref = observed_at or utc_now()
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        today = ref.astimezone(app_tz()).date()

    start_day = _local_date(time_start, fallback=today)
    finish_day = _local_date(time_finish, fallback=today)

    if not status_raw:
        return STATUS_UNKNOWN_BITRIX
    s = status_raw.strip().upper()

    if s in ("PAUSED", "PAUSE"):
        return STATUS_PAUSED

    if s in ("OPENED", "OPEN", "START", "STARTED"):
        if start_day is not None and start_day == today:
            return STATUS_WORKING
        if start_day is not None and start_day < today:
            return STATUS_STALE_UNCLOSED
        return STATUS_WORKING

    if s == "EXPIRED":
        if start_day is not None and start_day < today:
            return STATUS_STALE_UNCLOSED
        if start_day == today:
            # Expired same calendar day — still an unclosed day, but not multi-day stale
            return STATUS_STALE_UNCLOSED
        return STATUS_STALE_UNCLOSED

    if s in ("CLOSED", "CLOSE", "COMPLETED"):
        if time_start is None and time_finish is None:
            return STATUS_NOT_STARTED
        if start_day == today or finish_day == today:
            return STATUS_CLOSED
        # Closed day from the past — no open day today
        return STATUS_NOT_STARTED

    return STATUS_UNKNOWN_BITRIX


def classify_current_status(
    *,
    status_raw: str | None,
    time_start: datetime | None,
    time_finish: datetime | None,
    observed_at: datetime | None,
    today: date | None = None,
) -> dict[str, Any]:
    """Board-facing current Timeman state from latest snapshot (not today-join)."""
    from app.core.timezone import utc_now

    if today is None:
        today = utc_now().astimezone(app_tz()).date()

    if observed_at is None and status_raw is None and time_start is None:
        return {
            "status_normalized": STATUS_NO_DATA,
            "status_label": STATUS_LABELS_RU[STATUS_NO_DATA],
            "is_stale_unclosed": False,
            "stale_since_date": None,
            "stale_since_label": None,
            "tooltip": None,
            "today_metrics_applicable": False,
        }

    normalized = normalize_timeman_status(
        status_raw,
        time_start=time_start,
        time_finish=time_finish,
        observed_at=observed_at,
        today=today,
    )
    start_day = _local_date(time_start, fallback=today)
    finish_day = _local_date(time_finish, fallback=today)
    is_stale = normalized == STATUS_STALE_UNCLOSED
    stale_since = start_day if is_stale and start_day is not None else None

    today_applicable = False
    if normalized in (STATUS_WORKING, STATUS_PAUSED) and start_day == today:
        today_applicable = True
    elif normalized == STATUS_CLOSED and (start_day == today or finish_day == today):
        today_applicable = True
    elif normalized == STATUS_NOT_STARTED:
        today_applicable = True  # status is about today; times stay null

    label = STATUS_LABELS_RU.get(normalized, STATUS_LABELS_RU[STATUS_UNKNOWN_BITRIX])
    stale_label = None
    tooltip = None
    if is_stale and stale_since is not None:
        stale_label = f"с {format_date_ru(stale_since)}"
        tooltip = "Bitrix возвращает незакрытый рабочий день с прошлой даты."

    return {
        "status_normalized": normalized,
        "status_label": label,
        "is_stale_unclosed": is_stale,
        "stale_since_date": stale_since.isoformat() if stale_since else None,
        "stale_since_label": stale_label,
        "tooltip": tooltip,
        "today_metrics_applicable": today_applicable,
    }


def should_upsert_workday_history(
    *,
    status_normalized: str,
    work_date: date,
    observed_at: datetime,
) -> bool:
    """Do not invent past history rows from stale EXPIRED snapshots."""
    obs = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=timezone.utc)
    today = obs.astimezone(app_tz()).date()
    if status_normalized == STATUS_STALE_UNCLOSED and work_date < today:
        return False
    return True


@dataclass(frozen=True)
class ParsedTimemanStatus:
    status_raw: str | None
    status_normalized: str
    time_start: datetime | None
    time_finish: datetime | None
    duration_seconds: int | None
    duration_raw: str | None
    time_leaks_seconds: int | None
    time_leaks_raw: str | None
    source_timezone: str | None
    tz_offset_seconds: int | None
    work_date: date
    content_hash: str
    raw_summary: dict[str, Any]
    has_bitrix_timestamps: bool


def parse_timeman_status_payload(
    result: dict[str, Any],
    *,
    observed_at: datetime,
    app_timezone_name: str,
) -> ParsedTimemanStatus:
    status_raw = result.get("STATUS")
    if status_raw is not None:
        status_raw = str(status_raw)

    time_start = parse_bitrix_datetime(result.get("TIME_START"))
    time_finish = parse_bitrix_datetime(result.get("TIME_FINISH"))

    duration_raw = result.get("DURATION")
    duration_raw_s = str(duration_raw) if duration_raw is not None else None
    duration_seconds = parse_hms_to_seconds(duration_raw)

    leaks_raw = result.get("TIME_LEAKS")
    leaks_raw_s = str(leaks_raw) if leaks_raw is not None else None
    time_leaks_seconds = parse_hms_to_seconds(leaks_raw)

    tz_offset = result.get("TZ_OFFSET")
    tz_offset_seconds: int | None = None
    if tz_offset is not None and tz_offset != "":
        try:
            tz_offset_seconds = int(tz_offset)
        except (TypeError, ValueError):
            tz_offset_seconds = None

    source_timezone = app_timezone_name
    if tz_offset_seconds is not None:
        hours = tz_offset_seconds / 3600
        source_timezone = f"bitrix_offset_{hours:+g}h/{app_timezone_name}"

    if time_start is not None:
        work_date = time_start.astimezone(app_tz()).date()
    else:
        obs = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=timezone.utc)
        work_date = obs.astimezone(app_tz()).date()

    status_normalized = normalize_timeman_status(
        status_raw,
        time_start=time_start,
        time_finish=time_finish,
        observed_at=observed_at,
    )

    summary = {
        "STATUS": status_raw,
        "TIME_START_present": time_start is not None,
        "TIME_FINISH_present": time_finish is not None,
        "DURATION": duration_raw_s,
        "TIME_LEAKS": leaks_raw_s,
        "ACTIVE": result.get("ACTIVE"),
        "TZ_OFFSET": tz_offset_seconds,
        "keys": sorted(str(k) for k in result.keys()),
    }

    hash_payload = {
        "status": status_raw,
        "time_start": time_start.isoformat() if time_start else None,
        "time_finish": time_finish.isoformat() if time_finish else None,
        "duration": duration_raw_s,
        "leaks": leaks_raw_s,
        "tz_offset": tz_offset_seconds,
        "work_date": work_date.isoformat(),
    }
    content_hash = hashlib.sha256(
        json.dumps(hash_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    return ParsedTimemanStatus(
        status_raw=status_raw,
        status_normalized=status_normalized,
        time_start=time_start,
        time_finish=time_finish,
        duration_seconds=duration_seconds,
        duration_raw=duration_raw_s,
        time_leaks_seconds=time_leaks_seconds,
        time_leaks_raw=leaks_raw_s,
        source_timezone=source_timezone,
        tz_offset_seconds=tz_offset_seconds,
        work_date=work_date,
        content_hash=content_hash,
        raw_summary=summary,
        has_bitrix_timestamps=time_start is not None or time_finish is not None,
    )


def status_label_ru(normalized: str) -> str:
    return STATUS_LABELS_RU.get(normalized, STATUS_LABELS_RU[STATUS_UNKNOWN_BITRIX])


def build_simple_timeline(
    *,
    time_start: datetime | None,
    time_finish: datetime | None,
    duration_seconds: int | None,
    time_leaks_seconds: int | None,
    status_normalized: str,
) -> list[dict[str, Any]]:
    """Timeline for a valid today workday only (caller filters stale)."""
    events: list[dict[str, Any]] = []
    if status_normalized == STATUS_STALE_UNCLOSED:
        return events
    if time_start is not None:
        events.append(
            {
                "kind": "start",
                "label": "Начало рабочего дня",
                "at": time_start.isoformat(),
                "source": "bitrix",
            }
        )
    if time_leaks_seconds and time_leaks_seconds > 0:
        events.append(
            {
                "kind": "breaks",
                "label": "Перерывы (агрегировано Timeman)",
                "duration_seconds": time_leaks_seconds,
                "duration_display": format_seconds(time_leaks_seconds),
                "source": "bitrix",
            }
        )
    if time_finish is not None:
        events.append(
            {
                "kind": "finish",
                "label": "Конец рабочего дня",
                "at": time_finish.isoformat(),
                "source": "bitrix",
            }
        )
    elif status_normalized in (STATUS_WORKING, STATUS_PAUSED) and time_start is not None:
        events.append(
            {
                "kind": "in_progress",
                "label": "Рабочий день ещё не завершён",
                "duration_seconds": duration_seconds,
                "duration_display": format_seconds(duration_seconds),
                "source": "derived",
            }
        )
    return events


def local_dates_back(n: int, *, today: date | None = None) -> list[date]:
    from app.core.timezone import utc_now

    if today is None:
        today = utc_now().astimezone(app_tz()).date()
    return [today - timedelta(days=i) for i in range(n - 1, -1, -1)]

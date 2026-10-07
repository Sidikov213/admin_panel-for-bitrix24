from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def app_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().APP_TIMEZONE)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def local_day_bounds(d: date) -> tuple[datetime, datetime]:
    """Return UTC datetimes for start/end of calendar day in app timezone."""
    tz = app_tz()
    start = datetime.combine(d, time.min, tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(d, time.max, tzinfo=tz).astimezone(timezone.utc)
    return start, end


def parse_bitrix_datetime(value: object) -> datetime | None:
    """Parse Bitrix ISO-like datetime strings; missing/invalid → None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None

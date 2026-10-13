"""Parse Avito messenger/item payloads for probe analytics (no writes)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_avito_timestamp(value: Any) -> datetime | None:
    """Avito messenger `created` is typically Unix seconds; accept ISO too."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # Heuristic: ms vs s
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            return parse_avito_timestamp(int(s))
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def normalize_direction(raw: Any) -> str | None:
    """Return 'in' | 'out' | None.

    Avito docs: direction `in` = from customer, `out` = from seller/account.
    """
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in {"in", "incoming", "from_user", "u2i_in"}:
        return "in"
    if s in {"out", "outgoing", "from_me", "u2i_out"}:
        return "out"
    return None


def first_response_times(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute T1 (first customer), T2 (first seller reply after T1) if possible."""
    timed: list[tuple[datetime, str, dict[str, Any]]] = []
    for m in messages:
        ts = parse_avito_timestamp(m.get("created") if "created" in m else m.get("created_at"))
        direction = normalize_direction(m.get("direction"))
        if ts is None or direction is None:
            continue
        timed.append((ts, direction, m))
    timed.sort(key=lambda x: x[0])

    t1 = next((ts for ts, d, _ in timed if d == "in"), None)
    t2 = None
    if t1 is not None:
        t2 = next((ts for ts, d, _ in timed if d == "out" and ts >= t1), None)

    delta = None
    if t1 is not None and t2 is not None:
        delta = (t2 - t1).total_seconds()

    return {
        "customer_first_at": t1.isoformat() if t1 else None,
        "manager_first_reply_at": t2.isoformat() if t2 else None,
        "first_response_seconds": delta,
        "messages_with_direction": len(timed),
        "messages_total": len(messages),
    }


def extract_top_level_keys(obj: Any, *, limit: int = 40) -> list[str]:
    if not isinstance(obj, dict):
        return []
    return sorted(list(obj.keys()))[:limit]

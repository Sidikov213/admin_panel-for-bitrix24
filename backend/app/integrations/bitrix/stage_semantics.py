"""Map Bitrix stage semantics to Focus Analytics values.

Primary source (live-confirmed): crm.status.list → SEMANTICS (S/F/P)
and deal.STAGE_SEMANTIC_ID.

Documented fallback: systemic STATUS_ID suffixes :WON / :LOSE / :LOST
(not stage display names).
"""

from __future__ import annotations


def map_bitrix_semantics(value: object) -> str | None:
    """Normalize Bitrix SEMANTICS / STAGE_SEMANTIC_ID to success|failure|process."""
    if value is None or value == "":
        return None
    v = str(value).strip()
    low = v.lower()
    if low in {"success", "failure", "process"}:
        return low
    up = v.upper()
    if up in {"S", "SUCCESS"}:
        return "success"
    if up in {"F", "FAILURE", "FAIL"}:
        return "failure"
    if up in {"P", "PROCESS"}:
        return "process"
    return None


def semantics_from_stage_id(stage_id: object) -> str | None:
    """Documented fallback from systemic Bitrix stage STATUS_ID suffixes."""
    if stage_id is None or stage_id == "":
        return None
    s = str(stage_id).strip().upper()
    if s == "WON" or s.endswith(":WON"):
        return "success"
    if s in {"LOSE", "LOST"} or s.endswith(":LOSE") or s.endswith(":LOST"):
        return "failure"
    return None


def resolve_stage_semantics(*, raw_semantics: object = None, stage_id: object = None) -> str | None:
    """Prefer explicit Bitrix semantics; fall back to STATUS_ID suffix."""
    return map_bitrix_semantics(raw_semantics) or semantics_from_stage_id(stage_id)


def status_entity_id_for_category(category_id: int) -> str:
    """Bitrix crm.status.list ENTITY_ID for a deal category."""
    if int(category_id) == 0:
        return "DEAL_STAGE"
    return f"DEAL_STAGE_{int(category_id)}"

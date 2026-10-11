"""Stage-specific rules override pipeline/global for the same check."""

from __future__ import annotations

from typing import Any

from app.models.sales_rules import SalesRule

# Checks that a rule may define (attr → whether "set" means enforce)
CHECK_ATTRS = (
    "future_activity_required",
    "overdue_activity_allowed",
    "max_idle_minutes",
    "max_stage_duration_minutes",
    "max_next_activity_minutes",
    "required_fields",
    "required_comment",
    "comment_max_age_minutes",
)


def rule_specificity(rule: SalesRule) -> tuple[int, int]:
    """Higher = more specific. Stage > pipeline > global."""
    stage_score = 2 if rule.stage_id is not None else 0
    pipe_score = 1 if rule.pipeline_bitrix_id is not None else 0
    return (stage_score, pipe_score)


def rule_matches_deal(rule: SalesRule, *, category_id: int | None, stage_id: int | None) -> bool:
    if rule.pipeline_bitrix_id is not None and rule.pipeline_bitrix_id != category_id:
        return False
    if rule.stage_id is not None and rule.stage_id != stage_id:
        return False
    return True


def defines_check(rule: SalesRule, attr: str) -> bool:
    val = getattr(rule, attr, None)
    if attr == "future_activity_required":
        return val is True
    if attr == "overdue_activity_allowed":
        return val is False  # only enforce when overdue is NOT allowed
    if attr == "required_comment":
        return val is True
    if attr == "required_fields":
        return bool(val)
    return val is not None


def pick_rules_by_check(matching: list[SalesRule]) -> dict[str, SalesRule]:
    """For each check attr, pick the most specific matching rule that defines it."""
    chosen: dict[str, SalesRule] = {}
    for attr in CHECK_ATTRS:
        candidates = [r for r in matching if defines_check(r, attr)]
        if not candidates:
            continue
        candidates.sort(key=rule_specificity, reverse=True)
        chosen[attr] = candidates[0]
    return chosen


def serialize_rule(rule: SalesRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "rule_name": rule.rule_name,
        "description": rule.description,
        "pipeline_bitrix_id": rule.pipeline_bitrix_id,
        "stage_id": rule.stage_id,
        "enabled": rule.enabled,
        "max_idle_minutes": rule.max_idle_minutes,
        "future_activity_required": rule.future_activity_required,
        "max_next_activity_minutes": rule.max_next_activity_minutes,
        "overdue_activity_allowed": rule.overdue_activity_allowed,
        "required_fields": rule.required_fields,
        "required_comment": rule.required_comment,
        "comment_max_age_minutes": rule.comment_max_age_minutes,
        "max_stage_duration_minutes": rule.max_stage_duration_minutes,
        "severity": rule.severity,
        "comments_capability": rule.comments_capability,
    }

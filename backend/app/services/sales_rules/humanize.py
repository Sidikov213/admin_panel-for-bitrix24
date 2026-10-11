"""Human-readable rule descriptions for admin UI."""

from __future__ import annotations

from typing import Any


SEVERITY_RU = {
    "low": "LOW",
    "medium": "MEDIUM",
    "high": "HIGH",
    "critical": "CRITICAL",
}


def describe_rule(
    rule: dict[str, Any],
    *,
    pipeline_name: str | None = None,
    stage_name: str | None = None,
) -> str:
    scope_parts: list[str] = []
    if stage_name:
        scope_parts.append(f'этапа «{stage_name}»')
    elif rule.get("stage_id"):
        scope_parts.append(f"этапа id={rule['stage_id']}")
    if pipeline_name:
        scope_parts.append(f'воронки «{pipeline_name}»')
    elif rule.get("pipeline_bitrix_id") is not None:
        scope_parts.append(f"воронки CATEGORY_ID={rule['pipeline_bitrix_id']}")
    if not scope_parts:
        scope = "всех активных сделок"
    else:
        scope = " и ".join(scope_parts)

    sev = SEVERITY_RU.get(str(rule.get("severity") or "medium"), "MEDIUM")
    lines: list[str] = [f"Для {scope}:"]
    checks: list[str] = []

    if rule.get("future_activity_required") is True:
        checks.append(f"если нет следующего дела → нарушение {sev}")
    if rule.get("overdue_activity_allowed") is False:
        checks.append(f"если есть просроченное незавершённое дело → нарушение {sev}")
    if rule.get("max_idle_minutes"):
        checks.append(
            f"если нет наблюдаемого движения дольше {rule['max_idle_minutes']} мин → нарушение {sev}"
        )
    if rule.get("max_stage_duration_minutes"):
        checks.append(
            f"если сделка на этапе дольше {rule['max_stage_duration_minutes']} мин → нарушение {sev}"
        )
    if rule.get("max_next_activity_minutes"):
        checks.append(
            f"если следующее дело дальше чем через {rule['max_next_activity_minutes']} мин → нарушение {sev}"
        )
    fields = rule.get("required_fields") or []
    if fields:
        checks.append(f"если не заполнены поля [{', '.join(fields)}] → нарушение {sev}")
    if rule.get("required_comment") or rule.get("comment_max_age_minutes"):
        checks.append(
            "проверка комментариев недоступна (нет READ ONLY sync timeline/comments) — capability disabled"
        )

    if not checks:
        checks.append("пороги не заданы — правило не создаст нарушений")

    for c in checks:
        lines.append(f"• {c}")
    if not rule.get("enabled"):
        lines.append("Статус: выключено (не применяется до enable).")
    return "\n".join(lines)

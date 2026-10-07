from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.timezone import utc_now

# Until sales department approves regulations, rules mode is disabled (not company SLA).
RULES_ENABLED = False


@dataclass
class StalledRulesConfig:
    """Configurable stalled-deal rules — placeholders, not company SLA."""

    min_hours_since_last_activity: float = 48.0
    min_hours_since_stage_change: float = 72.0
    require_no_future_activity: bool = True


def is_stalled(
    *,
    last_observed_activity_at: datetime | None,
    stage_changed_observed_at: datetime | None,
    has_future_activity: bool,
    closed: bool,
    config: StalledRulesConfig | None = None,
) -> tuple[bool, str | None]:
    if closed:
        return False, None
    cfg = config or StalledRulesConfig()
    if cfg.require_no_future_activity and has_future_activity:
        return False, None
    now = utc_now()
    reasons: list[str] = []
    if last_observed_activity_at:
        delta = now - last_observed_activity_at
        if delta >= timedelta(hours=cfg.min_hours_since_last_activity):
            hours = int(delta.total_seconds() // 3600)
            reasons.append(f"нет активности {hours} ч (наблюдаемо)")
    if stage_changed_observed_at:
        delta = now - stage_changed_observed_at
        if delta >= timedelta(hours=cfg.min_hours_since_stage_change):
            hours = int(delta.total_seconds() // 3600)
            reasons.append(f"стадия без движения {hours} ч (наблюдаемо)")
    if not reasons and cfg.require_no_future_activity and not has_future_activity:
        reasons.append("нет следующего запланированного дела")
    if reasons:
        return True, "; ".join(reasons)
    return False, None

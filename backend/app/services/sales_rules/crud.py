"""Sales rules CRUD + audit trail."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import utc_now
from app.models.crm import CrmPipeline, CrmStage
from app.models.sales_rules import SalesRule, SalesRuleAudit
from app.services.sales_rules.humanize import describe_rule
from app.services.sales_rules.priority import serialize_rule


async def list_rules(session: AsyncSession) -> list[SalesRule]:
    return list((await session.execute(select(SalesRule).order_by(SalesRule.id.desc()))).scalars().all())


async def get_rule(session: AsyncSession, rule_id: int) -> SalesRule | None:
    return await session.get(SalesRule, rule_id)


async def _names(session: AsyncSession, rule: SalesRule) -> tuple[str | None, str | None]:
    pipe_name = None
    stage_name = None
    if rule.pipeline_bitrix_id is not None:
        pipe = (
            await session.execute(
                select(CrmPipeline).where(CrmPipeline.bitrix_id == rule.pipeline_bitrix_id)
            )
        ).scalar_one_or_none()
        pipe_name = pipe.name if pipe else None
    if rule.stage_id is not None:
        stage = await session.get(CrmStage, rule.stage_id)
        stage_name = stage.name if stage else None
    return pipe_name, stage_name


async def rule_with_description(session: AsyncSession, rule: SalesRule) -> dict[str, Any]:
    data = serialize_rule(rule)
    pipe_name, stage_name = await _names(session, rule)
    data["pipeline_name"] = pipe_name
    data["stage_name"] = stage_name
    data["human_description"] = describe_rule(data, pipeline_name=pipe_name, stage_name=stage_name)
    return data


async def write_audit(
    session: AsyncSession,
    *,
    rule_id: int | None,
    user_id: int | None,
    user_email: str | None,
    action: str,
    before: dict | None,
    after: dict | None,
) -> None:
    session.add(
        SalesRuleAudit(
            rule_id=rule_id,
            user_id=user_id,
            user_email=user_email,
            action=action,
            before=before,
            after=after,
            created_at=utc_now(),
        )
    )


def _apply_fields(rule: SalesRule, data: dict[str, Any]) -> None:
    for k, v in data.items():
        if hasattr(rule, k):
            setattr(rule, k, v)
    # Comment capability always unsupported until timeline sync
    if rule.required_comment or rule.comment_max_age_minutes:
        rule.comments_capability = "unsupported"
    else:
        rule.comments_capability = "unsupported"


async def create_rule(
    session: AsyncSession,
    data: dict[str, Any],
    *,
    user_id: int | None,
    user_email: str | None,
) -> SalesRule:
    rule = SalesRule()
    _apply_fields(rule, data)
    # Default disabled unless explicitly enabled
    if "enabled" not in data:
        rule.enabled = False
    session.add(rule)
    await session.flush()
    after = serialize_rule(rule)
    action = "enable" if rule.enabled else "create"
    await write_audit(
        session,
        rule_id=rule.id,
        user_id=user_id,
        user_email=user_email,
        action=action,
        before=None,
        after=after,
    )
    return rule


async def update_rule(
    session: AsyncSession,
    rule: SalesRule,
    data: dict[str, Any],
    *,
    user_id: int | None,
    user_email: str | None,
) -> SalesRule:
    before = serialize_rule(rule)
    was_enabled = rule.enabled
    _apply_fields(rule, data)
    await session.flush()
    after = serialize_rule(rule)
    if "enabled" in data and data["enabled"] != was_enabled:
        action = "enable" if rule.enabled else "disable"
    else:
        action = "update"
    await write_audit(
        session,
        rule_id=rule.id,
        user_id=user_id,
        user_email=user_email,
        action=action,
        before=before,
        after=after,
    )
    return rule


async def delete_rule(
    session: AsyncSession,
    rule: SalesRule,
    *,
    user_id: int | None,
    user_email: str | None,
) -> None:
    before = serialize_rule(rule)
    rid = rule.id
    await write_audit(
        session,
        rule_id=rid,
        user_id=user_id,
        user_email=user_email,
        action="delete",
        before=before,
        after=None,
    )
    await session.delete(rule)

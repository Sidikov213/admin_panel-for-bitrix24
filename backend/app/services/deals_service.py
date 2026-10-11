from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.timezone import utc_now
from app.models.crm import CrmPipeline, CrmStage, DealSnapshot
from app.repositories.deals import DealRepository
from app.schemas.deals import (
    ActivityOut,
    ChangeEventOut,
    DealDetailOut,
    DealListResponse,
    DealOut,
    SnapshotOut,
    TimelineItem,
)


class DealsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DealRepository(session)

    async def list_deals(self, **kwargs) -> DealListResponse:
        items, total = await self._repo.list_deals(**kwargs)
        return DealListResponse(
            items=[DealOut.model_validate(i) for i in items],
            total=total,
            offset=kwargs.get("offset", 0),
            limit=kwargs.get("limit", 50),
        )

    async def get_deal(self, deal_id: int) -> DealOut | None:
        deal = await self._repo.get_by_id(deal_id)
        return DealOut.model_validate(deal) if deal else None

    async def get_deal_detail(self, deal_id: int) -> DealDetailOut | None:
        deal = await self._repo.get_by_id(deal_id)
        if not deal:
            return None
        activities = await self._repo.list_activities_for_deal(deal.bitrix_id)
        events = await self._repo.list_change_events(deal.id)
        snapshots = (
            await self._session.execute(
                select(DealSnapshot)
                .where(DealSnapshot.deal_id == deal.id)
                .order_by(DealSnapshot.observed_at.desc())
                .limit(20)
            )
        ).scalars().all()

        settings = get_settings()
        bitrix_url = None
        if settings.BITRIX_PORTAL_URL:
            portal = settings.BITRIX_PORTAL_URL.rstrip("/")
            bitrix_url = f"{portal}/crm/deal/details/{deal.bitrix_id}/"

        now = utc_now()
        hours_without = None
        ref = deal.last_observed_activity_at or deal.stage_changed_observed_at or deal.date_modify
        if ref and not deal.closed:
            hours_without = round((now - ref).total_seconds() / 3600, 1)

        act_outs = [ActivityOut.model_validate(a) for a in activities]
        overdue = [
            a for a in act_outs if not a.completed and a.deadline and a.deadline < now
        ]
        future = [
            a for a in act_outs if not a.completed and a.deadline and a.deadline >= now
        ]
        current = [a for a in act_outs if not a.completed]

        # Resolve stage names for timeline
        stage_ids: set[int] = set()
        for e in events:
            if e.field_name == "stage_id":
                for v in (e.old_value, e.new_value):
                    if v and str(v).isdigit():
                        stage_ids.add(int(v))
        stages_map: dict[int, str] = {}
        if stage_ids:
            rows = (
                await self._session.execute(select(CrmStage).where(CrmStage.id.in_(stage_ids)))
            ).scalars().all()
            stages_map = {s.id: s.name for s in rows}

        pipeline_name = None
        if deal.category_id is not None:
            pipe = (
                await self._session.execute(
                    select(CrmPipeline).where(CrmPipeline.bitrix_id == deal.category_id)
                )
            ).scalar_one_or_none()
            if pipe:
                pipeline_name = pipe.name

        timeline: list[TimelineItem] = []
        for e in events:
            title = e.field_name
            detail = f"{e.old_value or '—'} → {e.new_value or '—'}"
            if e.field_name == "stage_id":
                old_n = stages_map.get(int(e.old_value), e.old_value) if e.old_value and str(e.old_value).isdigit() else e.old_value
                new_n = stages_map.get(int(e.new_value), e.new_value) if e.new_value and str(e.new_value).isdigit() else e.new_value
                title = "Этап изменён"
                detail = f"{old_n or '—'} → {new_n or '—'}"
            elif e.field_name == "opportunity":
                title = "Сумма"
            elif e.field_name == "assigned_by_id":
                title = "Менеджер"
            at = e.bitrix_event_at or e.observed_at
            is_observed = e.bitrix_event_at is None
            timeline.append(
                TimelineItem(
                    at=at,
                    kind=e.field_name,
                    title=title,
                    detail=detail,
                    is_observed=is_observed,
                    note=(
                        "observed_at — время обнаружения при синхронизации (polling), "
                        "не гарантирует точное время изменения в Bitrix"
                        if is_observed
                        else None
                    ),
                )
            )
        timeline.sort(key=lambda t: t.at, reverse=True)

        from app.services.sales_rules.aggregates import deal_violations

        violations = await deal_violations(self._session, deal.id)

        base = DealOut.model_validate(deal)
        return DealDetailOut(
            **base.model_dump(),
            activities=act_outs,
            current_activities=current,
            overdue_activities=overdue,
            future_activities=future,
            change_events=[
                ChangeEventOut(
                    id=e.id,
                    deal_id=e.deal_id,
                    field_name=e.field_name,
                    old_value=e.old_value,
                    new_value=e.new_value,
                    observed_at=e.observed_at,
                    bitrix_event_at=e.bitrix_event_at,
                    note=(
                        "observed_at — время обнаружения при синхронизации; "
                        "не гарантирует отсутствие промежуточных изменений"
                        if e.bitrix_event_at is None
                        else None
                    ),
                )
                for e in events
            ],
            timeline=timeline,
            snapshots=[
                SnapshotOut(
                    id=s.id,
                    observed_at=s.observed_at,
                    content_hash=s.content_hash,
                    payload_summary={
                        k: s.payload.get(k)
                        for k in ("TITLE", "STAGE_ID", "OPPORTUNITY", "ASSIGNED_BY_ID")
                        if isinstance(s.payload, dict) and k in s.payload
                    }
                    or None,
                )
                for s in snapshots
            ],
            pipeline_name=pipeline_name,
            no_future_activity_label=(
                "нет следующего запланированного дела" if not deal.has_future_activity else None
            ),
            bitrix_url=bitrix_url,
            hours_without_observed_movement=hours_without,
            violations=violations,
        )

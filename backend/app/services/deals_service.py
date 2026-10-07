from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.timezone import utc_now
from app.repositories.deals import DealRepository
from app.schemas.deals import (
    ActivityOut,
    ChangeEventOut,
    DealDetailOut,
    DealListResponse,
    DealOut,
)


class DealsService:
    def __init__(self, session: AsyncSession) -> None:
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
        settings = get_settings()
        bitrix_url = None
        if settings.BITRIX_PORTAL_URL:
            portal = settings.BITRIX_PORTAL_URL.rstrip("/")
            bitrix_url = f"{portal}/crm/deal/details/{deal.bitrix_id}/"

        hours_without = None
        ref = deal.last_observed_activity_at or deal.stage_changed_observed_at or deal.date_modify
        if ref and not deal.closed:
            hours_without = round((utc_now() - ref).total_seconds() / 3600, 1)

        base = DealOut.model_validate(deal)
        return DealDetailOut(
            **base.model_dump(),
            activities=[ActivityOut.model_validate(a) for a in activities],
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
            no_future_activity_label=(
                "нет следующего запланированного дела" if not deal.has_future_activity else None
            ),
            bitrix_url=bitrix_url,
            hours_without_observed_movement=hours_without,
        )

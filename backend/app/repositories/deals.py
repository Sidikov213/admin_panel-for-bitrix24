from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.crm import CrmActivity, CrmDeal, DealChangeEvent


class DealRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, deal_id: int) -> CrmDeal | None:
        stmt = (
            select(CrmDeal)
            .where(CrmDeal.id == deal_id)
            .options(selectinload(CrmDeal.stage), selectinload(CrmDeal.assigned_manager))
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_bitrix_id(self, bitrix_id: int) -> CrmDeal | None:
        stmt = select(CrmDeal).where(CrmDeal.bitrix_id == bitrix_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_deals(
        self,
        *,
        closed: bool | None = None,
        stage_id: int | None = None,
        manager_id: int | None = None,
        category_id: int | None = None,
        search: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        amount_min: Decimal | None = None,
        amount_max: Decimal | None = None,
        has_future_activity: bool | None = None,
        sort_by: str = "date_modify",
        sort_dir: str = "desc",
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[CrmDeal], int]:
        stmt = select(CrmDeal).options(
            selectinload(CrmDeal.stage), selectinload(CrmDeal.assigned_manager)
        )
        count_stmt = select(func.count()).select_from(CrmDeal)
        filters = [CrmDeal.missing_from_bitrix.is_(False)]
        if closed is not None:
            filters.append(CrmDeal.closed == closed)
        if stage_id is not None:
            filters.append(CrmDeal.stage_id == stage_id)
        if manager_id is not None:
            filters.append(CrmDeal.assigned_by_id == manager_id)
        if category_id is not None:
            filters.append(CrmDeal.category_id == category_id)
        if search:
            like = f"%{search}%"
            filters.append(
                or_(CrmDeal.title.ilike(like), cast(CrmDeal.bitrix_id, String).ilike(like))
            )
        if date_from is not None:
            filters.append(CrmDeal.date_create >= date_from)
        if date_to is not None:
            filters.append(CrmDeal.date_create <= date_to)
        if amount_min is not None:
            filters.append(CrmDeal.opportunity >= amount_min)
        if amount_max is not None:
            filters.append(CrmDeal.opportunity <= amount_max)
        if has_future_activity is not None:
            filters.append(CrmDeal.has_future_activity == has_future_activity)
        if filters:
            stmt = stmt.where(*filters)
            count_stmt = count_stmt.where(*filters)

        allowed_sort = {
            "date_modify",
            "date_create",
            "opportunity",
            "title",
            "next_deadline_at",
            "open_activities_count",
        }
        sort_col = getattr(CrmDeal, sort_by if sort_by in allowed_sort else "date_modify")
        if sort_dir == "asc":
            stmt = stmt.order_by(sort_col.asc().nullslast())
        else:
            stmt = stmt.order_by(sort_col.desc().nullslast())

        total = (await self._session.execute(count_stmt)).scalar_one()
        rows = (await self._session.execute(stmt.offset(offset).limit(limit))).scalars().all()
        return list(rows), total

    async def list_activities_for_deal(self, bitrix_deal_id: int) -> list[CrmActivity]:
        stmt = (
            select(CrmActivity)
            .where(CrmActivity.owner_type_id == 2, CrmActivity.owner_id == bitrix_deal_id)
            .order_by(CrmActivity.deadline.desc().nullslast())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_change_events(self, deal_id: int, limit: int = 50) -> list[DealChangeEvent]:
        stmt = (
            select(DealChangeEvent)
            .where(DealChangeEvent.deal_id == deal_id)
            .order_by(DealChangeEvent.observed_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

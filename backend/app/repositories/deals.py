from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analytics.kpi import overdue_activities_query
from app.core.timezone import local_day_bounds, utc_now
from app.models.crm import CrmActivity, CrmDeal, CrmStage, DealChangeEvent

OUTCOME_SEMANTICS = {"won": "success", "lost": "failure"}


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
        created_from: date | None = None,
        created_to: date | None = None,
        closed_from: date | None = None,
        closed_to: date | None = None,
        outcome: str | None = None,
        overdue: bool | None = None,
        sort_by: str = "date_modify",
        sort_dir: str = "desc",
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[CrmDeal], int]:
        """Filters mirror the dashboard KPIs so a KPI click lists exactly the counted deals.

        created_*/closed_* are local calendar days (APP_TIMEZONE); "closed" uses CLOSEDATE
        with date_modify fallback and outcome uses stage semantics — same as the won KPI.
        """
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
        if created_from is not None:
            filters.append(CrmDeal.date_create >= local_day_bounds(created_from)[0])
        if created_to is not None:
            filters.append(CrmDeal.date_create <= local_day_bounds(created_to)[1])
        closed_at = func.coalesce(CrmDeal.closedate, CrmDeal.date_modify)
        if closed_from is not None:
            filters += [CrmDeal.closed.is_(True), closed_at >= local_day_bounds(closed_from)[0]]
        if closed_to is not None:
            filters += [CrmDeal.closed.is_(True), closed_at <= local_day_bounds(closed_to)[1]]
        if outcome in OUTCOME_SEMANTICS:
            filters += [
                CrmDeal.closed.is_(True),
                CrmDeal.stage_id.in_(select(CrmStage.id).where(CrmStage.semantics == OUTCOME_SEMANTICS[outcome])),
            ]
        if overdue is not None:
            with_overdue = CrmDeal.bitrix_id.in_(overdue_activities_query(utc_now(), CrmActivity.owner_id))
            filters.append(with_overdue if overdue else ~with_overdue)
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
        # Tie-breaker by id: equal sort values must not shuffle rows between pages
        if sort_dir == "asc":
            stmt = stmt.order_by(sort_col.asc().nullslast(), CrmDeal.id)
        else:
            stmt = stmt.order_by(sort_col.desc().nullslast(), CrmDeal.id.desc())

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

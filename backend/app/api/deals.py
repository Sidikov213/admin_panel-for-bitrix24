from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status

from app.auth.deps import CurrentUser, DbSession
from app.schemas.deals import DealDetailOut, DealListResponse, DealOut
from app.services.deals_service import DealsService

router = APIRouter()


@router.get("", response_model=DealListResponse)
async def list_deals(
    _user: CurrentUser,
    db: DbSession,
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
    sort_by: str = Query(default="date_modify"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> DealListResponse:
    return await DealsService(db).list_deals(
        closed=closed,
        stage_id=stage_id,
        manager_id=manager_id,
        category_id=category_id,
        search=search,
        date_from=date_from,
        date_to=date_to,
        amount_min=amount_min,
        amount_max=amount_max,
        has_future_activity=has_future_activity,
        sort_by=sort_by,
        sort_dir=sort_dir,
        offset=offset,
        limit=limit,
    )


@router.get("/{deal_id}", response_model=DealDetailOut)
async def get_deal(deal_id: int, _user: CurrentUser, db: DbSession) -> DealDetailOut:
    deal = await DealsService(db).get_deal_detail(deal_id)
    if not deal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
    return deal

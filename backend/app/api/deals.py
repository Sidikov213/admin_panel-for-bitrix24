import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from app.auth.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.timezone import app_tz, utc_now
from app.repositories.deals import DealRepository
from app.schemas.deals import DealDetailOut, DealListResponse
from app.services.deals_service import DealsService

router = APIRouter()

# Hard cap for one CSV file; the response headers say when it was truncated
EXPORT_MAX_ROWS = 10000


def deal_filters(
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
    created_from: date | None = Query(default=None, description="Создана с (день в APP_TIMEZONE)"),
    created_to: date | None = Query(default=None),
    closed_from: date | None = Query(default=None, description="Закрыта с (CLOSEDATE, иначе дата изменения)"),
    closed_to: date | None = Query(default=None),
    outcome: str | None = Query(default=None, pattern="^(won|lost)$"),
    overdue: bool | None = Query(default=None, description="Есть просроченное дело"),
    sort_by: str = Query(default="date_modify"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> dict[str, Any]:
    """Shared by the list and the CSV export so both always show the same deals."""
    return dict(locals())


DealFilters = Annotated[dict[str, Any], Depends(deal_filters)]


@router.get("", response_model=DealListResponse)
async def list_deals(
    _user: CurrentUser,
    db: DbSession,
    filters: DealFilters,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> DealListResponse:
    return await DealsService(db).list_deals(**filters, offset=offset, limit=limit)


def _csv_cell(value: object) -> str:
    text = "" if value is None else str(value)
    # Spreadsheet formula injection: deal titles are typed by CRM users
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def _local(ts: datetime | None) -> str:
    if ts is None:
        return ""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(app_tz()).strftime("%d.%m.%Y %H:%M")


@router.get("/export.csv")
async def export_deals(_user: CurrentUser, db: DbSession, filters: DealFilters) -> Response:
    """Deals matching the list filters as CSV for Excel (UTF-8 with BOM, `;` separator)."""
    rows, total = await DealRepository(db).list_deals(**filters, offset=0, limit=EXPORT_MAX_ROWS)
    portal = get_settings().BITRIX_PORTAL_URL.rstrip("/")
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(
        ["ID в Bitrix", "Название", "Этап", "Менеджер", "Сумма", "Валюта", "Создана", "Изменена", "Закрыта",
         "Статус", "Следующее дело", "Ссылка"]
    )
    for d in rows:
        writer.writerow(
            [
                _csv_cell(v)
                for v in (
                    d.bitrix_id,
                    d.title,
                    d.stage.name if d.stage else "",
                    f"{d.assigned_manager.last_name} {d.assigned_manager.name}".strip() if d.assigned_manager else "",
                    # Excel in the ru locale expects a decimal comma
                    f"{d.opportunity:.2f}".replace(".", ",") if d.opportunity is not None else "",
                    d.currency_id or "",
                    _local(d.date_create),
                    _local(d.date_modify),
                    _local(d.closedate or d.date_modify) if d.closed else "",
                    "закрыта" if d.closed else "в работе",
                    "есть" if d.has_future_activity else "нет",
                    f"{portal}/crm/deal/details/{d.bitrix_id}/" if portal else "",
                )
            ]
        )
    stamp = utc_now().astimezone(app_tz()).strftime("%Y-%m-%d_%H%M")
    return Response(
        content="﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="deals_{stamp}.csv"',
            "X-Total-Count": str(total),
            "X-Truncated": "true" if total > len(rows) else "false",
        },
    )


@router.get("/{deal_id}", response_model=DealDetailOut)
async def get_deal(deal_id: int, _user: CurrentUser, db: DbSession) -> DealDetailOut:
    deal = await DealsService(db).get_deal_detail(deal_id)
    if not deal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
    return deal

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.analytics.plan import targets_progress
from app.auth.csrf import validate_csrf
from app.auth.deps import AdminUser, CurrentUser, DbSession
from app.core.timezone import app_tz, utc_now
from app.models.crm import CrmManager
from app.models.sync import SalesTarget
from app.schemas.targets import MAX_TARGET_DAYS, SalesTargetCreate, SalesTargetOut, SalesTargetUpdate

router = APIRouter()


@router.get("", response_model=list[SalesTargetOut])
async def list_targets(_user: CurrentUser, db: DbSession) -> list[SalesTargetOut]:
    rows = (await db.execute(select(SalesTarget).order_by(SalesTarget.period_start.desc()))).scalars().all()
    return [SalesTargetOut.model_validate(r) for r in rows]


@router.get("/progress")
async def list_progress(
    _user: CurrentUser,
    db: DbSession,
    on: date | None = Query(default=None, description="Дата расчёта (по умолчанию сегодня в APP_TIMEZONE)"),
    active_only: bool = Query(default=True),
    manager_id: int | None = Query(default=None),
) -> dict:
    day = on or utc_now().astimezone(app_tz()).date()
    items = await targets_progress(db, day, active_only=active_only, manager_id=manager_id)
    return {
        "on": day.isoformat(),
        "items": [p.to_dict() for p in items],
        "note": "Факт — сумма выигранных сделок (CLOSEDATE, иначе дата изменения) за период цели.",
    }


async def _validate_target(db: DbSession, row: SalesTarget, *, exclude_id: int | None = None) -> None:
    if row.period_end < row.period_start:
        raise HTTPException(status_code=422, detail="Дата окончания раньше даты начала")
    if (row.period_end - row.period_start).days + 1 > MAX_TARGET_DAYS:
        raise HTTPException(status_code=422, detail=f"Период цели не может быть длиннее {MAX_TARGET_DAYS} дней")
    if row.manager_id is not None and await db.get(CrmManager, row.manager_id) is None:
        raise HTTPException(status_code=422, detail="Менеджер не найден")
    # The DB unique constraint does not catch department targets: NULL manager_id never collides
    dup = select(SalesTarget.id).where(
        SalesTarget.manager_id.is_(None) if row.manager_id is None else SalesTarget.manager_id == row.manager_id,
        SalesTarget.period_type == row.period_type,
        SalesTarget.period_start == row.period_start,
        SalesTarget.period_end == row.period_end,
    )
    if exclude_id is not None:
        dup = dup.where(SalesTarget.id != exclude_id)
    if (await db.execute(dup)).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Такая цель уже есть")


async def _flush_or_conflict(db: DbSession) -> None:
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Такая цель уже есть") from None


@router.post("", response_model=SalesTargetOut, status_code=status.HTTP_201_CREATED)
async def create_target(
    body: SalesTargetCreate,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> SalesTargetOut:
    validate_csrf(request, csrf_header)
    row = SalesTarget(**body.model_dump())
    await _validate_target(db, row)
    db.add(row)
    await _flush_or_conflict(db)
    return SalesTargetOut.model_validate(row)


@router.patch("/{target_id}", response_model=SalesTargetOut)
async def update_target(
    target_id: int,
    body: SalesTargetUpdate,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> SalesTargetOut:
    validate_csrf(request, csrf_header)
    row = await db.get(SalesTarget, target_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
    changes = body.model_dump(exclude_unset=True)
    for k in ("period_type", "period_start", "period_end", "amount", "currency"):
        if k in changes and changes[k] is None:
            raise HTTPException(status_code=422, detail=f"{k} не может быть пустым")
    for k, v in changes.items():
        setattr(row, k, v)
    # Validate the merged state; autoflush is off for the duplicate lookup
    with db.no_autoflush:
        await _validate_target(db, row, exclude_id=row.id)
    await _flush_or_conflict(db)
    return SalesTargetOut.model_validate(row)


@router.delete("/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(
    target_id: int,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    validate_csrf(request, csrf_header)
    row = await db.get(SalesTarget, target_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
    await db.delete(row)

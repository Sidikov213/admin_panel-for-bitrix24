from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import select

from app.auth.csrf import validate_csrf
from app.auth.deps import AdminUser, CurrentUser, DbSession
from app.models.sync import SalesTarget
from app.schemas.targets import SalesTargetCreate, SalesTargetOut, SalesTargetUpdate

router = APIRouter()


@router.get("", response_model=list[SalesTargetOut])
async def list_targets(_user: CurrentUser, db: DbSession) -> list[SalesTargetOut]:
    rows = (await db.execute(select(SalesTarget).order_by(SalesTarget.period_start.desc()))).scalars().all()
    return [SalesTargetOut.model_validate(r) for r in rows]


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
    db.add(row)
    await db.flush()
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
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    await db.flush()
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

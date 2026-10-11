from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.deps import AdminUser, CurrentUser, DbSession
from app.services import manager_control_service as svc
from app.services import monitored_roster as roster

router = APIRouter()


class RosterPatch(BaseModel):
    include: bool | None = None
    exclude: bool | None = None
    note: str | None = Field(default=None, max_length=500)


@router.get("")
async def manager_control_list(_user: CurrentUser, db: DbSession) -> dict:
    return await svc.list_manager_control(db)


@router.get("/roster")
async def manager_control_roster(_admin: AdminUser, db: DbSession) -> dict:
    items = await roster.list_roster_admin(db)
    return {"items": items, "total": len(items)}


@router.patch("/roster/{manager_id}")
async def patch_manager_roster(
    manager_id: int,
    body: RosterPatch,
    _admin: AdminUser,
    db: DbSession,
) -> dict:
    try:
        row = await roster.set_manual_monitor(
            db,
            manager_id,
            include=body.include,
            exclude=body.exclude,
            note=body.note,
        )
        await db.commit()
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found") from None
    return {
        "manager_id": row.manager_id,
        "manual_include": row.manual_include,
        "manual_exclude": row.manual_exclude,
        "auto_included": row.auto_included,
        "monitored": roster.is_monitored_row(row),
        "note": row.note,
    }


@router.get("/{manager_id}")
async def manager_control_detail(
    manager_id: int,
    _user: CurrentUser,
    db: DbSession,
) -> dict:
    data = await svc.get_manager_control_detail(db, manager_id)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found")
    return data

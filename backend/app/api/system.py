from fastapi import APIRouter

from app.auth.deps import CurrentUser, DbSession
from app.services.system_service import SystemService

router = APIRouter()


@router.get("")
async def system_status(_user: CurrentUser, db: DbSession) -> dict:
    return await SystemService(db).get_status()

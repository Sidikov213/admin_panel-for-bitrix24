from typing import Annotated

from fastapi import APIRouter, Header, Request
from sqlalchemy import func, select

from app.auth.csrf import validate_csrf
from app.auth.deps import AdminUser, CurrentUser, DbSession
from app.core.config import get_settings
from app.models.crm import CrmManager
from app.notifications.digest import build_digest, render_manager_digest, render_team_digest, to_plain_text
from app.notifications.service import LAST_DIGEST_STATE, send_daily_digest
from app.repositories.sync import SyncRepository

router = APIRouter()


@router.get("/status")
async def notifications_status(_user: CurrentUser, db: DbSession) -> dict:
    settings = get_settings()
    managers_with_chat = (
        await db.execute(select(func.count()).select_from(CrmManager).where(CrmManager.telegram_chat_id.isnot(None)))
    ).scalar_one()
    return {
        "telegram_configured": settings.telegram_configured,
        "team_chat_configured": bool(settings.TELEGRAM_CHAT_ID.strip()),
        "enabled": settings.DIGEST_ENABLED,
        "days": settings.DIGEST_DAYS,
        "time": settings.DIGEST_TIME,
        "timezone": settings.APP_TIMEZONE,
        "stale_days": settings.DIGEST_STALE_DAYS,
        "managers_with_chat": managers_with_chat,
        "last_sent": await SyncRepository(db).get_state(LAST_DIGEST_STATE),
    }


@router.get("/digest/preview")
async def digest_preview(_admin: AdminUser, db: DbSession) -> dict:
    """Plain-text preview of what would be sent now (no markup sent to the browser)."""
    digest = await build_digest(db)
    return {
        "date": digest.day.isoformat(),
        "team": to_plain_text(render_team_digest(digest)),
        "managers": [
            {
                "manager_id": m.manager_id,
                "name": m.name,
                "has_chat": bool(m.telegram_chat_id),
                "text": to_plain_text(render_manager_digest(digest, m)),
            }
            for m in digest.managers_all
            if m.telegram_chat_id or m.has_problems
        ],
    }


@router.post("/digest/send")
async def digest_send(
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    validate_csrf(request, csrf_header)
    return await send_daily_digest(db, force=True)

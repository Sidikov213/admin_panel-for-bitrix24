from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.analytics.avito import account_names, avito_summary, chat_url
from app.auth.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.timezone import app_tz, utc_now
from app.integrations.avito.sync import STATE_KEY
from app.models.avito import AvitoChat, AvitoMessage
from app.models.sync import SyncRun, SyncType
from app.repositories.sync import SyncRepository

router = APIRouter()


@router.get("/status")
async def avito_status(_user: CurrentUser, db: DbSession) -> dict:
    """Configured accounts (names only — secrets never leave the environment) and last sync."""
    s = get_settings()
    try:
        accounts = s.avito_accounts
        config_error = None
    except ValueError as e:
        accounts, config_error = [], str(e)
    state = await SyncRepository(db).get_state(STATE_KEY) or {}
    last_run = (
        await db.execute(select(SyncRun).where(SyncRun.sync_type == SyncType.avito).order_by(SyncRun.started_at.desc()).limit(1))
    ).scalar_one_or_none()
    per_account = (last_run.cursor_info or {}).get("accounts", {}) if last_run else {}
    return {
        "configured": bool(accounts),
        "config_error": config_error,
        "accounts": [
            {
                "id": a["id"],
                "name": a["name"],
                "last_sync_at": (state.get(str(a["id"])) or {}).get("at"),
                "last_error": (per_account.get(str(a["id"])) or {}).get("error"),
            }
            for a in accounts
        ],
        "last_run": (
            {"status": last_run.status.value, "started_at": last_run.started_at.isoformat(), "error": last_run.error_message}
            if last_run
            else None
        ),
        "reply_norm_minutes": s.AVITO_REPLY_NORM_MINUTES,
    }


@router.get("/summary")
async def summary(
    _user: CurrentUser,
    db: DbSession,
    period_start: date | None = None,
    period_end: date | None = None,
    account_id: int | None = None,
) -> dict:
    end = period_end or utc_now().astimezone(app_tz()).date()
    start = period_start or end - timedelta(days=29)
    if start > end:
        raise HTTPException(status_code=422, detail="Начало периода позже конца")
    if (end - start).days > 366:
        raise HTTPException(status_code=422, detail="Период не может быть длиннее года")
    return await avito_summary(db, period_start=start, period_end=end, account_id=account_id)


@router.get("/chats/{chat_id}")
async def chat_messages(chat_id: str, _user: CurrentUser, db: DbSession) -> dict:
    chat = (await db.execute(select(AvitoChat).where(AvitoChat.chat_id == chat_id))).scalar_one_or_none()
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Диалог не найден")
    msgs = (
        await db.execute(
            select(AvitoMessage).where(AvitoMessage.chat_id == chat_id).order_by(AvitoMessage.created, AvitoMessage.id)
        )
    ).scalars().all()
    return {
        "chat_id": chat.chat_id,
        "account": account_names().get(chat.account_id, str(chat.account_id)),
        "client_name": chat.client_name,
        "item_title": chat.item_title,
        "item_url": chat.item_url,
        "chat_url": chat_url(chat.chat_id),
        "deal_bitrix_id": chat.deal_bitrix_id,
        "messages": [
            {"id": m.message_id, "direction": m.direction, "created": m.created.isoformat(), "text": m.text,
             "is_system": m.is_system}
            for m in msgs
        ],
    }

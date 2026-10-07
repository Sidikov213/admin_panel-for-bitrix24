from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.security import generate_csrf_token, generate_session_token, hash_token
from app.core.timezone import utc_now
from app.models.auth import Session, User


async def create_session(db: AsyncSession, user: User) -> tuple[str, str, Session]:
    settings = get_settings()
    raw_token = generate_session_token()
    csrf = generate_csrf_token()
    row = Session(
        token_hash=hash_token(raw_token),
        user_id=user.id,
        expires_at=utc_now() + timedelta(hours=settings.SESSION_TTL_HOURS),
        csrf_token=csrf,
    )
    db.add(row)
    await db.flush()
    return raw_token, csrf, row


async def get_session_by_token(db: AsyncSession, raw_token: str) -> Session | None:
    token_hash = hash_token(raw_token)
    stmt = (
        select(Session)
        .where(Session.token_hash == token_hash, Session.expires_at > utc_now())
        .options(selectinload(Session.user))
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def delete_session_by_token(db: AsyncSession, raw_token: str) -> None:
    token_hash = hash_token(raw_token)
    await db.execute(delete(Session).where(Session.token_hash == token_hash))


async def delete_user_sessions(db: AsyncSession, user_id: int) -> None:
    await db.execute(delete(Session).where(Session.user_id == user_id))

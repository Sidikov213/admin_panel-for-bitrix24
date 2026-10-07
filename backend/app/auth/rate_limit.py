from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.timezone import utc_now
from app.models.auth import LoginAttempt


async def is_login_locked(session: AsyncSession, ip: str, email: str) -> bool:
    settings = get_settings()
    since = utc_now() - timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
    stmt = (
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.ip == ip,
            LoginAttempt.email == email.lower(),
            LoginAttempt.attempted_at >= since,
        )
    )
    count = (await session.execute(stmt)).scalar_one()
    return count >= settings.LOGIN_MAX_ATTEMPTS


async def record_login_attempt(session: AsyncSession, ip: str, email: str) -> None:
    session.add(
        LoginAttempt(
            ip=ip,
            email=email.lower(),
            attempted_at=utc_now(),
        )
    )
    await session.flush()

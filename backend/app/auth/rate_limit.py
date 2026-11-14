import ipaddress
from datetime import timedelta

from fastapi import Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.timezone import utc_now
from app.models.auth import LoginAttempt

# One address trying many emails
IP_LIMIT_MULTIPLIER = 6
# Many addresses trying one email. Above the per-address limit on purpose: a single
# stranger must not be able to lock the owner out by typing wrong passwords for them.
EMAIL_LIMIT_MULTIPLIER = 20


def _is_trusted(addr: str, networks: list[str]) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    for net in networks:
        try:
            if ip in ipaddress.ip_network(net, strict=False):
                return True
        except ValueError:
            continue
    return False


def client_ip(request: Request) -> str:
    """Address of the visitor, not of our own reverse proxy.

    The API sits behind the frontend / Caddy, so the socket peer is always a container.
    X-Forwarded-For is read only when the peer is a trusted proxy, from the right: the
    first hop that is not ours is the visitor (anything further left is client-supplied).
    """
    peer = request.client.host if request.client else "unknown"
    trusted = get_settings().trusted_proxies
    if not trusted or not _is_trusted(peer, trusted):
        return peer
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(hops):
        if not _is_trusted(hop, trusted):
            return hop[:45]
    return peer


async def _count(session: AsyncSession, *where) -> int:
    settings = get_settings()
    since = utc_now() - timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
    stmt = select(func.count()).select_from(LoginAttempt).where(LoginAttempt.attempted_at >= since, *where)
    return (await session.execute(stmt)).scalar_one()


async def is_login_locked(session: AsyncSession, ip: str, email: str) -> bool:
    limit = get_settings().LOGIN_MAX_ATTEMPTS
    email = email.lower()
    if await _count(session, LoginAttempt.ip == ip, LoginAttempt.email == email) >= limit:
        return True
    if await _count(session, LoginAttempt.ip == ip) >= limit * IP_LIMIT_MULTIPLIER:
        return True
    return await _count(session, LoginAttempt.email == email) >= limit * EMAIL_LIMIT_MULTIPLIER


async def record_login_attempt(session: AsyncSession, ip: str, email: str) -> None:
    session.add(
        LoginAttempt(
            ip=ip,
            email=email.lower(),
            attempted_at=utc_now(),
        )
    )
    await session.flush()


async def forget_login_attempts(session: AsyncSession, ip: str, email: str) -> None:
    """After a successful login: old typos from this address stop counting, old rows get purged."""
    settings = get_settings()
    stale = utc_now() - timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
    await session.execute(delete(LoginAttempt).where(LoginAttempt.ip == ip, LoginAttempt.email == email.lower()))
    await session.execute(delete(LoginAttempt).where(LoginAttempt.attempted_at < stale))

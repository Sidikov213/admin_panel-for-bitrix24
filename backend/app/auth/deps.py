from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.csrf import validate_csrf
from app.auth.session import get_session_by_token
from app.core.config import get_settings
from app.db.session import get_db
from app.models.auth import User, UserRole


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    session_cookie: Annotated[str | None, Cookie(alias="focus_session")] = None,
) -> User:
    settings = get_settings()
    token = session_cookie or request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    sess = await get_session_by_token(db, token)
    if not sess or not sess.user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    return sess.user


async def get_current_user_optional(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    settings = get_settings()
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        return None
    sess = await get_session_by_token(db, token)
    if not sess or not sess.user.is_active:
        return None
    return sess.user


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user


async def require_csrf(
    request: Request,
    csrf_header: Annotated[str | None, Depends(lambda: None)] = None,
) -> None:
    from fastapi import Header

    header = request.headers.get("X-CSRF-Token")
    validate_csrf(request, header)


CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(User.email == email.lower())
    return (await db.execute(stmt)).scalar_one_or_none()

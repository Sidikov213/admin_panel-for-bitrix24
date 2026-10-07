from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status

from app.auth.deps import CurrentUser, DbSession, get_user_by_email
from app.auth.password import verify_password
from app.auth.rate_limit import is_login_locked, record_login_attempt
from app.auth.session import create_session, delete_session_by_token
from app.core.config import get_settings
from app.schemas.auth import CsrfOut, LoginRequest, UserOut

router = APIRouter()


def _set_session_cookies(response: Response, session_token: str, csrf: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.SESSION_TTL_HOURS * 3600,
        path="/",
    )
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=csrf,
        httponly=False,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.SESSION_TTL_HOURS * 3600,
        path="/",
    )


@router.post("/login", response_model=UserOut)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> UserOut:
    ip = request.client.host if request.client else "unknown"
    email = body.email.lower()
    if await is_login_locked(db, ip, email):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts")
    user = await get_user_by_email(db, email)
    if not user or not verify_password(body.password, user.password_hash):
        await record_login_attempt(db, ip, email)
        # Commit before HTTPException — otherwise dependency rollback drops attempts
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    token, csrf, _ = await create_session(db, user)
    await db.commit()
    _set_session_cookies(response, token, csrf)
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    db: DbSession,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    from app.auth.csrf import validate_csrf

    validate_csrf(request, csrf_header)
    settings = get_settings()
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if token:
        await delete_session_by_token(db, token)
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(settings.CSRF_COOKIE_NAME, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.get("/csrf", response_model=CsrfOut)
async def csrf_token(request: Request) -> CsrfOut:
    settings = get_settings()
    token = request.cookies.get(settings.CSRF_COOKIE_NAME, "")
    return CsrfOut(csrf_token=token)

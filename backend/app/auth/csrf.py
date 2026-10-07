from fastapi import Header, HTTPException, Request, status

from app.core.config import get_settings


def validate_csrf(request: Request, csrf_header: str | None = Header(default=None, alias="X-CSRF-Token")) -> None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    cookie = request.cookies.get(get_settings().CSRF_COOKIE_NAME)
    if not cookie or not csrf_header or cookie != csrf_header:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")

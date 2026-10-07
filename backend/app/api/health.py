from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.auth.deps import DbSession

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: process is up. Does not check dependencies."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(response: Response, db: DbSession) -> dict[str, str]:
    """Readiness: database session must answer SELECT 1."""
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "ok"}
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "database": "unavailable"}

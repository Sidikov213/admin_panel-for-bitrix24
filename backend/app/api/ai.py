from datetime import date
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.ai.provider import AIError
from app.ai.service import analyze_period, brief, calls_today, present
from app.auth.csrf import validate_csrf
from app.auth.deps import AdminUser, CurrentUser, DbSession
from app.core.config import get_settings
from app.models.analytics import AIAnalysis
from app.reports.builder import local_today, period_for

router = APIRouter()

# AI error kind → HTTP status shown to the panel
ERROR_STATUS = {"not_configured": 409, "limit": 429, "rate_limit": 429, "auth": 502, "refusal": 502,
                "bad_output": 502, "unavailable": 503}


@router.get("/status")
async def ai_status(_user: CurrentUser, db: DbSession) -> dict:
    s = get_settings()
    return {
        "configured": s.ai_configured,
        "model": s.AI_MODEL,
        "effort": s.AI_EFFORT,
        "send_texts": s.AI_SEND_TEXTS,
        "in_reports": s.AI_REPORTS,
        "script_configured": bool(s.AI_SALES_SCRIPT.strip()),
        "daily_limit": s.AI_DAILY_LIMIT,
        "used_today": await calls_today(db),
    }


@router.get("/analyses")
async def list_analyses(
    _user: CurrentUser,
    db: DbSession,
    kind: str | None = Query(default=None, pattern="^(daily|weekly|monthly)$"),
    limit: int = Query(default=30, ge=1, le=200),
) -> dict:
    stmt = select(AIAnalysis).order_by(AIAnalysis.id.desc()).limit(limit)
    if kind:
        stmt = stmt.where(AIAnalysis.kind == kind)
    return {"items": [brief(r) for r in (await db.execute(stmt)).scalars().all()]}


@router.get("/analyses/{analysis_id}")
async def get_analysis(analysis_id: int, _user: CurrentUser, db: DbSession) -> dict:
    row = await db.get(AIAnalysis, analysis_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Анализ не найден")
    return await present(db, row, with_context=True)


class RunIn(BaseModel):
    kind: str = Field(pattern="^(daily|weekly|monthly)$")
    # Any day inside the wanted day / week / month; default today
    day: date | None = None
    # Ask the model again even if the numbers did not change
    force: bool = False


@router.post("/analyses")
async def run_analysis(
    body: RunIn,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    validate_csrf(request, csrf_header)
    ref = body.day or local_today()
    if ref > local_today():
        raise HTTPException(status_code=422, detail="Анализ будущего периода не строится")
    start, end = period_for(body.kind, ref)
    try:
        row = await analyze_period(db, body.kind, start, end, force=body.force)
    except AIError as e:
        raise HTTPException(status_code=ERROR_STATUS.get(e.kind, 503), detail=str(e)) from e
    return await present(db, row, with_context=True)

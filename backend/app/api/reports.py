from datetime import date
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.analytics.kpi import compute_period_kpis
from app.auth.csrf import validate_csrf
from app.auth.deps import AdminUser, CurrentUser, DbSession
from app.core.config import get_settings
from app.models.analytics import SalesReport
from app.notifications.digest import to_plain_text
from app.reports.builder import local_today, period_for
from app.reports.service import generate_report, send_report

router = APIRouter()


@router.get("")
async def reports(
    _user: CurrentUser,
    db: DbSession,
    period_start: date = Query(...),
    period_end: date = Query(...),
    pipeline_id: int | None = None,
    manager_id: int | None = None,
) -> dict:
    metrics = await compute_period_kpis(db, period_start, period_end, pipeline_id, manager_id)
    return {"report": metrics}


def _brief(r: SalesReport) -> dict:
    m = (r.data or {}).get("metrics", {})
    return {
        "id": r.id,
        "kind": r.kind,
        "title": (r.data or {}).get("title"),
        "period_start": r.period_start.isoformat(),
        "period_end": r.period_end.isoformat(),
        "generated_at": (r.data or {}).get("generated_at"),
        "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        "sent_to": r.sent_to,
        "send_error": r.send_error,
        "headline": {k: m.get(k) for k in ("new", "won", "lost", "overdue", "stuck_now")},
    }


@router.get("/archive")
async def list_archive(
    _user: CurrentUser,
    db: DbSession,
    kind: str | None = Query(default=None, pattern="^(daily|weekly|monthly)$"),
    limit: int = Query(default=30, ge=1, le=200),
) -> dict:
    stmt = select(SalesReport).order_by(SalesReport.period_start.desc(), SalesReport.id.desc()).limit(limit)
    if kind:
        stmt = stmt.where(SalesReport.kind == kind)
    rows = (await db.execute(stmt)).scalars().all()
    s = get_settings()
    return {
        "items": [_brief(r) for r in rows],
        "schedule": {
            "enabled": s.REPORTS_ENABLED,
            "daily_time": s.REPORT_DAILY_TIME,
            "weekly_day": s.REPORT_WEEKLY_DAY,
            "weekly_time": s.REPORT_WEEKLY_TIME,
            "telegram_configured": s.telegram_configured,
            "recipients": len(s.report_chat_ids),
        },
    }


@router.get("/archive/{report_id}")
async def get_archived(report_id: int, _user: CurrentUser, db: DbSession) -> dict:
    r = await db.get(SalesReport, report_id)
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Отчёт не найден")
    # Plain text only: no markup reaches the browser
    return {**_brief(r), "data": r.data, "text": to_plain_text(r.text)}


class GenerateIn(BaseModel):
    kind: str = Field(pattern="^(daily|weekly|monthly)$")
    # Any day inside the wanted day / week / month; default today
    day: date | None = None


@router.post("/archive/generate")
async def generate(
    body: GenerateIn,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    validate_csrf(request, csrf_header)
    ref = body.day or local_today()
    if ref > local_today():
        raise HTTPException(status_code=422, detail="Отчёт за будущий период не строится")
    start, end = period_for(body.kind, ref)
    r = await generate_report(db, body.kind, start, end)
    return _brief(r)


@router.post("/archive/{report_id}/send")
async def send(
    report_id: int,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    validate_csrf(request, csrf_header)
    r = await db.get(SalesReport, report_id)
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Отчёт не найден")
    return await send_report(db, r)

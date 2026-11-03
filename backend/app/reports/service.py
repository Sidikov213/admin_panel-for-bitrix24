"""Generate, archive and send reports."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.timezone import utc_now
from app.core.work_calendar import get_work_calendar
from app.models.analytics import SalesReport
from app.notifications.telegram import TelegramClient, TelegramError
from app.reports.builder import build_report, local_today, render_report, report_period_for_schedule

logger = logging.getLogger(__name__)


async def generate_report(session: AsyncSession, kind: str, start: date, end: date) -> SalesReport:
    """Build (or rebuild) the report for the period; keeps the sending history."""
    data = await build_report(session, kind, start, end)
    from app.ai.service import summary_for_report

    data["ai_summary"] = await summary_for_report(session, kind, start, end, data)
    row = (
        await session.execute(
            select(SalesReport).where(
                SalesReport.kind == kind, SalesReport.period_start == start, SalesReport.period_end == end
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = SalesReport(kind=kind, period_start=start, period_end=end)
        session.add(row)
    row.data = data
    row.text = render_report(data)
    await session.flush()
    await session.commit()
    return row


async def send_report(session: AsyncSession, report: SalesReport, client: TelegramClient | None = None) -> dict[str, Any]:
    settings = get_settings()
    recipients = settings.report_chat_ids
    if not settings.telegram_configured:
        return {"status": "skipped", "reason": "telegram_not_configured"}
    if not recipients:
        return {"status": "skipped", "reason": "no_recipients"}
    client = client or TelegramClient(settings.TELEGRAM_BOT_TOKEN)
    sent, errors = 0, []
    for chat in recipients:
        try:
            await client.send_message(chat, report.text)
            sent += 1
        except TelegramError as e:
            errors.append(f"{chat}: {e}")
            logger.warning("report_send_failed report_id=%s err=%s", report.id, e)
    if sent:
        report.sent_at = utc_now()
    report.sent_to = sent
    report.send_error = "; ".join(errors) or None
    await session.commit()
    return {"status": "sent" if sent else "failed", "sent_to": sent, "errors": errors}


async def run_scheduled_report(
    session: AsyncSession, kind: str, *, today: date | None = None, client: TelegramClient | None = None
) -> dict[str, Any]:
    """Scheduler entry point: archive the report, send it once."""
    today = today or local_today()
    if kind == "daily" and not get_work_calendar().is_workday(today):
        return {"status": "skipped", "reason": "not_a_workday", "date": today.isoformat()}
    start, end = report_period_for_schedule(kind, today)
    report = await generate_report(session, kind, start, end)
    if report.sent_at is not None:
        return {"status": "skipped", "reason": "already_sent", "report_id": report.id}
    result = await send_report(session, report, client=client)
    logger.info("report_done kind=%s period=%s..%s status=%s", kind, start, end, result["status"])
    return {**result, "report_id": report.id}

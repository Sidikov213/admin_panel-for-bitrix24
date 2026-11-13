import asyncio
import logging
from datetime import datetime, time, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.timezone import app_tz
from app.core.work_calendar import parse_hours, parse_weekdays
from app.integrations.bitrix.client import BitrixClient
from app.db.session import async_session_factory
from app.models.sync import SyncRun, SyncStatus, SyncType
from app.notifications.service import send_daily_digest
from app.integrations.avito.sync import run_avito_sync
from app.reports.service import run_scheduled_report
from app.repositories.sync import SyncRepository
from app.services.sync_service import SyncOrchestrator

logger = logging.getLogger(__name__)

# A report whose time passed while the worker was down is still sent within this window
REPORT_CATCH_UP = timedelta(hours=3)
# The first cycle after a start may be long; the interval job must not run on top of it
_cycle_lock = asyncio.Lock()


async def run_sync_cycle(*, full_reconcile: bool = False) -> bool:
    """Run dictionaries → deals → activities → stage history → comments. Returns True if deal phase succeeded."""
    settings = get_settings()
    if not settings.BITRIX_WEBHOOK_URL:
        logger.info("sync_skip_bitrix_not_configured")
        return False

    # One client for the whole cycle: its connection pool is reused by every phase
    client = BitrixClient()
    try:
        async with async_session_factory() as session:
            await SyncOrchestrator(session, client).run_dictionaries()
        async with async_session_factory() as session:
            await SyncOrchestrator(session, client).run_deals(full=full_reconcile)
        async with async_session_factory() as session:
            # Full activity pull only on full reconcile; otherwise LAST_UPDATED delta
            await SyncOrchestrator(session, client).run_activities(full=full_reconcile)
        async with async_session_factory() as session:
            # ID cursor: always incremental, the first run backfills history
            await SyncOrchestrator(session, client).run_stage_history()
        async with async_session_factory() as session:
            await SyncOrchestrator(session, client).run_comments()
    finally:
        await client.aclose()

    async with async_session_factory() as session:
        sync_type = SyncType.full_reconcile if full_reconcile else SyncType.deals
        latest = (
            await session.execute(
                select(SyncRun)
                .where(SyncRun.sync_type == sync_type)
                .order_by(SyncRun.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return latest is not None and latest.status == SyncStatus.success


def full_reconcile_due(last: datetime | None, now: datetime) -> bool:
    """Full reconcile is long (every activity of the portal) and holds back the 5-minute sync.

    Once it is due it waits for the quiet window (FULL_RECONCILE_WINDOW, local time) so the
    working day keeps fresh data. A machine that is off at night never meets the window:
    after twice the interval the reconcile runs at the first chance.
    """
    settings = get_settings()
    if last is None:
        return True
    age = now - last
    interval = timedelta(hours=settings.FULL_RECONCILE_HOURS)
    if age < interval:
        return False
    window = settings.FULL_RECONCILE_WINDOW.strip()
    if not window or age >= 2 * interval:
        return True
    start, end = parse_hours(window)
    return start <= now.astimezone(app_tz()).time() < end


async def should_full_reconcile() -> bool:
    async with async_session_factory() as session:
        state = await SyncRepository(session).get_state("last_full_reconcile") or {}
    last = state.get("at")
    return full_reconcile_due(datetime.fromisoformat(last) if last else None, datetime.now(timezone.utc))


async def mark_full_reconcile() -> None:
    async with async_session_factory() as session:
        repo = SyncRepository(session)
        await repo.set_state("last_full_reconcile", {"at": datetime.now(timezone.utc).isoformat()})
        await session.commit()


async def scheduled_job() -> None:
    if _cycle_lock.locked():
        logger.info("sync_skip_cycle_running")
        return
    async with _cycle_lock:
        full = await should_full_reconcile()
        logger.info("sync_cycle_start full_reconcile=%s", full)
        ok = await run_sync_cycle(full_reconcile=full)
        # Only advance reconcile watermark after a successful full run
        if full and ok:
            await mark_full_reconcile()
        elif not ok:
            logger.warning("sync_cycle_failed watermark_not_advanced=%s", full)


async def digest_job() -> None:
    try:
        async with async_session_factory() as session:
            await send_daily_digest(session)
    except Exception:
        logger.exception("digest_job_failed")


async def avito_job() -> None:
    # Independent of Bitrix: Avito dialogs are useful even before the webhook is set
    try:
        async with async_session_factory() as session:
            await run_avito_sync(session)
    except Exception:
        logger.exception("avito_job_failed")


def digest_trigger() -> CronTrigger:
    settings = get_settings()
    hour, minute = (int(x) for x in settings.DIGEST_TIME.split(":"))
    return CronTrigger(day_of_week=settings.DIGEST_DAYS, hour=hour, minute=minute, timezone=app_tz())


async def report_job(kind: str) -> None:
    try:
        async with async_session_factory() as session:
            await run_scheduled_report(session, kind)
    except Exception:
        logger.exception("report_job_failed kind=%s", kind)


def report_triggers() -> dict[str, CronTrigger]:
    settings = get_settings()
    dh, dm = (int(x) for x in settings.REPORT_DAILY_TIME.split(":"))
    wh, wm = (int(x) for x in settings.REPORT_WEEKLY_TIME.split(":"))
    return {
        # Holidays inside WORK_DAYS are skipped by run_scheduled_report itself
        "daily": CronTrigger(day_of_week=settings.WORK_DAYS, hour=dh, minute=dm, timezone=app_tz()),
        "weekly": CronTrigger(day_of_week=settings.REPORT_WEEKLY_DAY, hour=wh, minute=wm, timezone=app_tz()),
    }


def missed_reports(now: datetime) -> list[str]:
    """Report kinds whose scheduled time passed at most REPORT_CATCH_UP ago today.

    The scheduler keeps its jobs in memory: a run missed while the worker was down is not
    fired on start. Sending is idempotent (a report already sent is skipped), so asking
    again after a restart is safe.
    """
    settings = get_settings()
    local = now.astimezone(app_tz())
    due: list[str] = []
    slots = {
        "daily": (parse_weekdays(settings.WORK_DAYS), settings.REPORT_DAILY_TIME),
        "weekly": (parse_weekdays(settings.REPORT_WEEKLY_DAY), settings.REPORT_WEEKLY_TIME),
    }
    for kind, (days, hhmm) in slots.items():
        if local.weekday() not in days:
            continue
        at = datetime.combine(local.date(), time.fromisoformat(hhmm), tzinfo=local.tzinfo)
        if at <= local <= at + REPORT_CATCH_UP:
            due.append(kind)
    return due


async def close_stale_runs() -> None:
    try:
        async with async_session_factory() as session:
            closed = await SyncOrchestrator(session).close_stale_runs()
        if closed:
            logger.warning("stale_sync_runs_closed count=%s", closed)
    except Exception:
        logger.exception("close_stale_runs_failed")


def main() -> None:
    setup_logging()
    settings = get_settings()
    scheduler = AsyncIOScheduler()
    # AsyncIOScheduler accepts coroutine callables directly — do not wrap in create_task
    scheduler.add_job(
        scheduled_job,
        "interval",
        minutes=settings.SYNC_INTERVAL_MINUTES,
        id="bitrix_sync",
        max_instances=1,
        coalesce=True,
    )
    if settings.DIGEST_ENABLED and settings.telegram_configured:
        scheduler.add_job(
            digest_job,
            digest_trigger(),
            id="daily_digest",
            max_instances=1,
            coalesce=True,
            # Worker restarted shortly after the scheduled time → still send today's digest
            misfire_grace_time=3 * 3600,
        )
        logger.info("digest_scheduled days=%s time=%s", settings.DIGEST_DAYS, settings.DIGEST_TIME)
    else:
        logger.info("digest_disabled")
    try:
        avito_accounts = settings.avito_accounts
    except ValueError:
        logger.exception("avito_config_invalid")
        avito_accounts = []
    if avito_accounts:
        scheduler.add_job(
            avito_job,
            "interval",
            minutes=settings.AVITO_SYNC_INTERVAL_MINUTES,
            id="avito_sync",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(timezone.utc),
        )
        logger.info("avito_scheduled accounts=%s", len(avito_accounts))
    if settings.REPORTS_ENABLED:
        # Reports are archived in the panel even without Telegram; sending is skipped then
        for kind, trigger in report_triggers().items():
            scheduler.add_job(
                report_job,
                trigger,
                args=[kind],
                id=f"report_{kind}",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=3 * 3600,
            )
        logger.info(
            "reports_scheduled daily=%s weekly=%s %s",
            settings.REPORT_DAILY_TIME,
            settings.REPORT_WEEKLY_DAY,
            settings.REPORT_WEEKLY_TIME,
        )

    async def bootstrap() -> None:
        logger.info("sync_worker_start")
        await close_stale_runs()
        # Start the scheduler first: reports and Avito must not wait for a long first sync
        scheduler.start()
        if not settings.BITRIX_WEBHOOK_URL:
            logger.info("bootstrap_skipped_bitrix_not_configured")
        else:
            try:
                # Incremental unless the full reconcile is due (see full_reconcile_due)
                await scheduled_job()
            except Exception:
                logger.exception("bootstrap_sync_crashed")
        if settings.REPORTS_ENABLED:
            for kind in missed_reports(datetime.now(timezone.utc)):
                logger.info("report_catch_up kind=%s", kind)
                await report_job(kind)
        while True:
            await asyncio.sleep(3600)

    asyncio.run(bootstrap())


if __name__ == "__main__":
    main()

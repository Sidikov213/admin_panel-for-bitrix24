import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.timezone import app_tz
from app.db.session import async_session_factory
from app.models.sync import SyncRun, SyncStatus, SyncType
from app.notifications.service import send_daily_digest
from app.reports.service import run_scheduled_report
from app.repositories.sync import SyncRepository
from app.services.sync_service import SyncOrchestrator

logger = logging.getLogger(__name__)


async def run_sync_cycle(*, full_reconcile: bool = False) -> bool:
    """Run dictionaries → deals → activities → stage history → comments. Returns True if deal phase succeeded."""
    settings = get_settings()
    if not settings.BITRIX_WEBHOOK_URL:
        logger.info("sync_skip_bitrix_not_configured")
        return False

    async with async_session_factory() as session:
        orchestrator = SyncOrchestrator(session)
        await orchestrator.run_dictionaries()
    async with async_session_factory() as session:
        orchestrator = SyncOrchestrator(session)
        await orchestrator.run_deals(full=full_reconcile)
    async with async_session_factory() as session:
        orchestrator = SyncOrchestrator(session)
        # Full activity pull only on full reconcile; otherwise LAST_UPDATED delta
        await orchestrator.run_activities(full=full_reconcile)
    async with async_session_factory() as session:
        # ID cursor: always incremental, the first run backfills history
        await SyncOrchestrator(session).run_stage_history()
    async with async_session_factory() as session:
        await SyncOrchestrator(session).run_comments()

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


async def should_full_reconcile() -> bool:
    settings = get_settings()
    async with async_session_factory() as session:
        repo = SyncRepository(session)
        state = await repo.get_state("last_full_reconcile") or {}
        last = state.get("at")
        if not last:
            return True
        dt = datetime.fromisoformat(last)
        return datetime.now(timezone.utc) - dt >= timedelta(hours=settings.FULL_RECONCILE_HOURS)


async def mark_full_reconcile() -> None:
    async with async_session_factory() as session:
        repo = SyncRepository(session)
        await repo.set_state("last_full_reconcile", {"at": datetime.now(timezone.utc).isoformat()})
        await session.commit()


async def scheduled_job() -> None:
    full = await should_full_reconcile()
    ok = await run_sync_cycle(full_reconcile=full)
    # Only advance reconcile watermark after a successful full run
    if full and ok:
        await mark_full_reconcile()


async def digest_job() -> None:
    try:
        async with async_session_factory() as session:
            await send_daily_digest(session)
    except Exception:
        logger.exception("digest_job_failed")


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
        if not settings.BITRIX_WEBHOOK_URL:
            logger.info("bootstrap_skipped_bitrix_not_configured")
        else:
            # After a successful full initial sync, bootstrap must be incremental.
            # Full reconcile only when last_full_reconcile is missing/stale.
            full = await should_full_reconcile()
            logger.info("bootstrap_sync_mode full_reconcile=%s", full)
            ok = await run_sync_cycle(full_reconcile=full)
            if full and ok:
                await mark_full_reconcile()
            elif not ok:
                logger.warning("bootstrap_sync_failed watermark_not_advanced=%s", full)
        scheduler.start()
        while True:
            await asyncio.sleep(3600)

    asyncio.run(bootstrap())


if __name__ == "__main__":
    main()

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import async_session_factory
from app.models.sync import SyncRun, SyncStatus, SyncType
from app.repositories.sync import SyncRepository
from app.services.sync_service import SyncOrchestrator

logger = logging.getLogger(__name__)


async def run_sync_cycle(*, full_reconcile: bool = False) -> bool:
    """Run dictionaries → deals → activities. Returns True if deal phase succeeded."""
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

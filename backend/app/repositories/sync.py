import zlib
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sync import SyncRun, SyncState, SyncStatus, SyncType
from app.db.locks import AdvisoryLock

# Stable across processes (unlike Python hash(), which is salted per process).
# deals + full_reconcile share one key so they cannot mutate CRM rows concurrently.
_LOCK_KEYS: dict[SyncType, int] = {
    SyncType.dictionaries: zlib.crc32(b"focus:sync:dictionaries") & 0x7FFFFFFF,
    SyncType.deals: zlib.crc32(b"focus:sync:deals") & 0x7FFFFFFF,
    SyncType.full_reconcile: zlib.crc32(b"focus:sync:deals") & 0x7FFFFFFF,
    SyncType.activities: zlib.crc32(b"focus:sync:activities") & 0x7FFFFFFF,
}


def advisory_lock_key(sync_type: SyncType) -> int:
    return _LOCK_KEYS[sync_type]


class SyncRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._locks: dict[int, AdvisoryLock] = {}

    async def try_advisory_lock(self, sync_type: SyncType) -> bool:
        key = advisory_lock_key(sync_type)
        lock = AdvisoryLock(self._session, key)
        if await lock.acquire():
            self._locks[key] = lock
            return True
        return False

    async def advisory_unlock(self, sync_type: SyncType) -> None:
        key = advisory_lock_key(sync_type)
        lock = self._locks.pop(key, None)
        if lock:
            await lock.release()

    async def start_run(self, sync_type: SyncType) -> SyncRun:
        from app.core.timezone import utc_now

        run = SyncRun(
            sync_type=sync_type,
            status=SyncStatus.running,
            started_at=utc_now(),
        )
        self._session.add(run)
        await self._session.flush()
        return run

    async def finish_run(
        self,
        run: SyncRun,
        *,
        status: SyncStatus,
        items_processed: int,
        errors_count: int,
        error_message: str | None = None,
        cursor_info: dict | None = None,
    ) -> None:
        from app.core.timezone import utc_now

        run.status = status
        run.finished_at = utc_now()
        run.items_processed = items_processed
        run.errors_count = errors_count
        run.error_message = error_message
        run.cursor_info = cursor_info
        await self._session.flush()

    async def get_state(self, key: str) -> dict | None:
        row = await self._session.get(SyncState, key)
        return row.value if row else None

    async def set_state(self, key: str, value: dict) -> None:
        from app.core.timezone import utc_now

        stmt = insert(SyncState).values(key=key, value=value, updated_at=utc_now())
        stmt = stmt.on_conflict_do_update(
            index_elements=[SyncState.key],
            set_={"value": value, "updated_at": utc_now()},
        )
        await self._session.execute(stmt)

    async def latest_run(self, sync_type: SyncType | None = None) -> SyncRun | None:
        stmt = select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1)
        if sync_type:
            stmt = stmt.where(SyncRun.sync_type == sync_type)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def recent_runs(self, limit: int = 10) -> list[SyncRun]:
        stmt = select(SyncRun).order_by(SyncRun.started_at.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    async def crm_freshness(self) -> dict:
        from app.analytics.freshness import _parse_ts, build_freshness
        stamps = [_parse_ts(await self.get_state(key)) for key in (
            "last_deals_sync", "last_activities_sync", "last_dictionaries_sync"
        )]
        runs = [await self.latest_run(t) for t in SyncType]
        deals = [r for r in runs if r and r.sync_type in (SyncType.deals, SyncType.full_reconcile)]
        phases = [r for r in runs if r and r.sync_type in (SyncType.activities, SyncType.dictionaries)]
        if deals:
            phases.append(max(deals, key=lambda r: r.started_at))
        failed = any(r.status == SyncStatus.failed for r in phases)
        return build_freshness(
            last_successful_sync_at=min(stamps) if all(stamps) else None,
            last_attempted_sync_at=max((r.started_at for r in phases), default=None),
            latest_run_status="failed" if failed else None,
        )

    async def latest_successful_run(self) -> SyncRun | None:
        stmt = (
            select(SyncRun)
            .where(SyncRun.status == SyncStatus.success)
            .order_by(SyncRun.finished_at.desc().nullslast())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def errors_and_retries_24h(self) -> dict:
        from datetime import timedelta

        from app.core.timezone import utc_now
        from sqlalchemy import func

        since = utc_now() - timedelta(hours=24)
        errors = (
            await self._session.execute(
                select(func.coalesce(func.sum(SyncRun.errors_count), 0)).where(SyncRun.started_at >= since)
            )
        ).scalar_one()
        failed_runs = (
            await self._session.execute(
                select(func.count()).select_from(SyncRun).where(
                    SyncRun.started_at >= since, SyncRun.status == SyncStatus.failed
                )
            )
        ).scalar_one()
        return {"errors_count_24h": int(errors or 0), "failed_runs_24h": int(failed_runs or 0)}

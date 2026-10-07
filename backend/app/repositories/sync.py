import zlib
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sync import SyncRun, SyncState, SyncStatus, SyncType

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

    async def try_advisory_lock(self, sync_type: SyncType) -> bool:
        key = advisory_lock_key(sync_type)
        result = await self._session.execute(
            text("SELECT pg_try_advisory_lock(:k)"),
            {"k": key},
        )
        return bool(result.scalar())

    async def advisory_unlock(self, sync_type: SyncType) -> None:
        key = advisory_lock_key(sync_type)
        await self._session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})

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

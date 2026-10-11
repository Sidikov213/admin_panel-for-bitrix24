"""Timeman collector — READ ONLY polling of timeman.status.

Isolated from CRM sync: failures here must never mark CRM sync as failed.
"""

from __future__ import annotations

import logging
import zlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.timezone import app_tz, utc_now
from app.integrations.bitrix.client import BitrixClient, BitrixClientError
from app.integrations.bitrix.sanitize import sanitize_bitrix_text
from app.models.crm import CrmManager
from app.models.manager_control import ManagerWorkday, ManagerWorkdaySnapshot
from app.repositories.sync import SyncRepository
from app.services.monitored_roster import list_monitored_managers, sync_monitored_roster
from app.services.timeman_parse import parse_timeman_status_payload, should_upsert_workday_history

logger = logging.getLogger(__name__)

STATE_LAST_SYNC = "last_timeman_sync"
STATE_HISTORY_SINCE = "timeman_history_since"

_LOCK_KEY = zlib.crc32(b"focus:sync:timeman") & 0x7FFFFFFF


@dataclass
class TimemanCollectResult:
    ok: bool
    managers_considered: int = 0
    snapshots_inserted: int = 0
    snapshots_deduped: int = 0
    workdays_upserted: int = 0
    errors: int = 0
    error_message: str | None = None
    last_updated_at: str | None = None


async def list_relevant_managers(
    session: AsyncSession,
    *,
    limit: int,
) -> list[CrmManager]:
    """Monitored sales managers (roster) — not Bitrix is_active alone."""
    managers = await list_monitored_managers(session)
    return managers[:limit]


async def _try_lock(session: AsyncSession) -> bool:
    try:
        result = await session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY})
        return bool(result.scalar())
    except Exception:
        # SQLite tests: advisory locks unavailable — proceed without lock
        return True


async def _unlock(session: AsyncSession) -> None:
    try:
        await session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
    except Exception:
        pass


async def upsert_workday_from_snapshot(
    session: AsyncSession,
    snap: ManagerWorkdaySnapshot,
) -> bool:
    """Merge snapshot into manager_workdays when appropriate. Skip stale EXPIRED history."""
    if not should_upsert_workday_history(
        status_normalized=snap.status_normalized,
        work_date=snap.work_date,
        observed_at=snap.observed_at,
    ):
        return False
    existing = (
        await session.execute(
            select(ManagerWorkday).where(
                ManagerWorkday.manager_id == snap.manager_id,
                ManagerWorkday.work_date == snap.work_date,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        session.add(
            ManagerWorkday(
                manager_id=snap.manager_id,
                work_date=snap.work_date,
                status_raw=snap.status_raw,
                status_normalized=snap.status_normalized,
                time_start=snap.time_start,
                time_finish=snap.time_finish,
                duration_seconds=snap.duration_seconds,
                time_leaks_seconds=snap.time_leaks_seconds,
                source_timezone=snap.source_timezone,
                last_observed_at=snap.observed_at,
                snapshot_count=1,
                has_bitrix_timestamps=bool(snap.time_start or snap.time_finish),
            )
        )
        return True

    existing.status_raw = snap.status_raw
    existing.status_normalized = snap.status_normalized
    # Prefer Bitrix timestamps when present
    if snap.time_start is not None:
        existing.time_start = snap.time_start
    if snap.time_finish is not None:
        existing.time_finish = snap.time_finish
    existing.duration_seconds = snap.duration_seconds
    existing.time_leaks_seconds = snap.time_leaks_seconds
    existing.source_timezone = snap.source_timezone
    existing.last_observed_at = snap.observed_at
    existing.snapshot_count = int(existing.snapshot_count or 0) + 1
    existing.has_bitrix_timestamps = bool(existing.time_start or existing.time_finish)
    return True


async def persist_parsed_status_safe(
    session: AsyncSession,
    *,
    manager: CrmManager,
    parsed: Any,
    observed_at: datetime,
) -> tuple[bool, bool]:
    """Insert snapshot with duplicate hash prevention. Returns (inserted, deduped)."""
    # Check existing hash first (works on SQLite + PG without relying on IntegrityError rollback)
    exists = (
        await session.execute(
            select(ManagerWorkdaySnapshot.id).where(
                ManagerWorkdaySnapshot.manager_id == manager.id,
                ManagerWorkdaySnapshot.content_hash == parsed.content_hash,
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        last = await session.get(ManagerWorkdaySnapshot, exists)
        if last is not None:
            last.observed_at = observed_at
            last.status_normalized = parsed.status_normalized
            await upsert_workday_from_snapshot(session, last)
            await session.flush()
        return False, True

    snap = ManagerWorkdaySnapshot(
        manager_id=manager.id,
        bitrix_user_id=manager.bitrix_id,
        observed_at=observed_at,
        work_date=parsed.work_date,
        status_raw=parsed.status_raw,
        status_normalized=parsed.status_normalized,
        time_start=parsed.time_start,
        time_finish=parsed.time_finish,
        duration_seconds=parsed.duration_seconds,
        duration_raw=parsed.duration_raw,
        time_leaks_seconds=parsed.time_leaks_seconds,
        time_leaks_raw=parsed.time_leaks_raw,
        source_timezone=parsed.source_timezone,
        tz_offset_seconds=parsed.tz_offset_seconds,
        content_hash=parsed.content_hash,
        raw_summary=parsed.raw_summary,
    )
    session.add(snap)
    await session.flush()
    await upsert_workday_from_snapshot(session, snap)
    await session.flush()
    return True, False


class TimemanCollector:
    def __init__(
        self,
        session: AsyncSession,
        client: BitrixClient | None = None,
    ) -> None:
        self._session = session
        settings = get_settings()
        self._client = client or BitrixClient(
            timeout=settings.TIMEMAN_REQUEST_TIMEOUT,
            max_retries=settings.TIMEMAN_RETRY_MAX,
        )

    async def run_cycle(self) -> TimemanCollectResult:
        settings = get_settings()
        if not settings.TIMEMAN_COLLECTOR_ENABLED:
            return TimemanCollectResult(ok=True, error_message="disabled")
        # Real BitrixClient without webhook cannot call; MagicMock/test clients skip this gate
        if isinstance(self._client, BitrixClient) and not self._client.webhook_configured:
            return TimemanCollectResult(ok=False, error_message="bitrix_not_configured")

        locked = await _try_lock(self._session)
        if not locked:
            logger.info("timeman_collector_skip_lock_held")
            return TimemanCollectResult(ok=True, error_message="lock_held")

        result = TimemanCollectResult(ok=True)
        observed_at = utc_now()
        try:
            await sync_monitored_roster(self._session)
            managers = await list_relevant_managers(
                self._session, limit=settings.TIMEMAN_MAX_MANAGERS_PER_CYCLE
            )
            result.managers_considered = len(managers)

            repo = SyncRepository(self._session)
            hist = await repo.get_state(STATE_HISTORY_SINCE)
            if not hist:
                await repo.set_state(
                    STATE_HISTORY_SINCE,
                    {
                        "at": observed_at.isoformat(),
                        "local_date": observed_at.astimezone(app_tz()).date().isoformat(),
                        "note": "Local Timeman history starts here",
                    },
                )

            for mgr in managers:
                try:
                    payload = await self._client.timeman_status(int(mgr.bitrix_id))
                    parsed = parse_timeman_status_payload(
                        payload,
                        observed_at=observed_at,
                        app_timezone_name=settings.APP_TIMEZONE,
                    )
                    inserted, deduped = await persist_parsed_status_safe(
                        self._session,
                        manager=mgr,
                        parsed=parsed,
                        observed_at=observed_at,
                    )
                    if inserted:
                        result.snapshots_inserted += 1
                        result.workdays_upserted += 1
                    if deduped:
                        result.snapshots_deduped += 1
                except BitrixClientError as e:
                    result.errors += 1
                    logger.warning(
                        "timeman_status_failed manager_id=%s kind=%s err=%s",
                        mgr.id,
                        e.kind,
                        sanitize_bitrix_text(str(e)),
                    )
                except Exception as e:
                    result.errors += 1
                    logger.warning(
                        "timeman_collect_manager_error manager_id=%s err=%s",
                        mgr.id,
                        type(e).__name__,
                    )

            await self._session.commit()

            result.last_updated_at = observed_at.isoformat()
            result.ok = result.errors == 0 or result.snapshots_inserted > 0 or result.snapshots_deduped > 0
            # Partial success still records freshness
            await repo.set_state(
                STATE_LAST_SYNC,
                {
                    "at": observed_at.isoformat(),
                    "ok": result.ok,
                    "managers": result.managers_considered,
                    "inserted": result.snapshots_inserted,
                    "deduped": result.snapshots_deduped,
                    "errors": result.errors,
                },
            )
            await self._session.commit()
            logger.info(
                "timeman_collector_done managers=%s inserted=%s deduped=%s errors=%s",
                result.managers_considered,
                result.snapshots_inserted,
                result.snapshots_deduped,
                result.errors,
            )
            return result
        except Exception as e:
            result.ok = False
            result.error_message = sanitize_bitrix_text(f"{type(e).__name__}: {e}")
            logger.exception("timeman_collector_failed")
            try:
                await self._session.rollback()
                repo = SyncRepository(self._session)
                await repo.set_state(
                    STATE_LAST_SYNC,
                    {
                        "at": observed_at.isoformat(),
                        "ok": False,
                        "error": result.error_message,
                    },
                )
                await self._session.commit()
            except Exception:
                pass
            return result
        finally:
            await _unlock(self._session)


async def run_timeman_collect_safe() -> dict[str, Any]:
    """Entry point for worker — never raises into CRM sync path."""
    from app.db.session import async_session_factory

    try:
        async with async_session_factory() as session:
            collector = TimemanCollector(session)
            result = await collector.run_cycle()
            return {
                "ok": result.ok,
                "managers": result.managers_considered,
                "inserted": result.snapshots_inserted,
                "deduped": result.snapshots_deduped,
                "errors": result.errors,
                "error_message": result.error_message,
                "at": result.last_updated_at,
            }
    except Exception as e:
        logger.exception("timeman_collect_safe_failed")
        return {"ok": False, "error_message": type(e).__name__}

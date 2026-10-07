import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.timezone import utc_now
from app.integrations.bitrix.client import BitrixClient
from app.repositories.sync import SyncRepository


class SystemService:
    _bitrix_cache: tuple[float, bool] | None = None
    _CACHE_TTL = 60.0

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sync_repo = SyncRepository(session)

    async def get_status(self) -> dict:
        settings = get_settings()
        last_deals = await self._sync_repo.get_state("last_deals_sync")
        last_activities = await self._sync_repo.get_state("last_activities_sync")
        last_dict = await self._sync_repo.get_state("last_dictionaries_sync")
        latest = await self._sync_repo.latest_run()
        recent_runs = await self._sync_repo.recent_runs(limit=10)
        bitrix_ok = await self._cached_bitrix_ping()

        data_may_be_stale = (not bitrix_ok) or (not settings.BITRIX_WEBHOOK_URL)
        if latest and latest.status.value == "failed":
            data_may_be_stale = True

        return {
            "demo_mode": settings.DEMO_MODE,
            "bitrix_configured": bool(settings.BITRIX_WEBHOOK_URL),
            "bitrix_reachable": bitrix_ok,
            "bitrix_portal_url": settings.BITRIX_PORTAL_URL or None,
            "category_ids": settings.bitrix_category_ids,
            "sync_interval_minutes": settings.SYNC_INTERVAL_MINUTES,
            "last_deals_sync": last_deals,
            "last_activities_sync": last_activities,
            "last_dictionaries_sync": last_dict,
            "data_may_be_stale": data_may_be_stale,
            "stale_note": (
                "Bitrix недоступен или не настроен — панель работает с последними "
                "сохранёнными данными. Показатели могут быть устаревшими."
                if data_may_be_stale
                else None
            ),
            "checked_at": utc_now().isoformat(),
            "latest_sync_run": _run_dict(latest) if latest else None,
            "recent_sync_runs": [_run_dict(r) for r in recent_runs],
            "integrations": {
                "bitrix": {
                    "status": (
                        "ok"
                        if bitrix_ok
                        else ("not_configured" if not settings.BITRIX_WEBHOOK_URL else "unreachable")
                    ),
                    "read_only": True,
                },
                "avito": {"status": "planned", "note": "В разработке"},
                "sla_adapter": {"status": "planned", "note": "Read-only adapter — этап 2"},
                "ai": {"status": "planned", "note": "Интерфейсы подготовлены, без внешних вызовов"},
            },
        }

    async def _cached_bitrix_ping(self) -> bool:
        now = time.monotonic()
        if self._bitrix_cache and now - self._bitrix_cache[0] < self._CACHE_TTL:
            return self._bitrix_cache[1]
        client = BitrixClient()
        ok = await client.ping() if get_settings().BITRIX_WEBHOOK_URL else False
        SystemService._bitrix_cache = (now, ok)
        return ok


def _run_dict(run) -> dict:
    return {
        "id": run.id,
        "sync_type": run.sync_type.value,
        "status": run.status.value,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "items_processed": run.items_processed,
        "errors_count": run.errors_count,
        "error_message": run.error_message,
        "duration_seconds": (
            (run.finished_at - run.started_at).total_seconds()
            if run.finished_at
            else None
        ),
    }

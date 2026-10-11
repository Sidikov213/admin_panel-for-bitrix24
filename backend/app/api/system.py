from fastapi import APIRouter
from sqlalchemy import func, select

from app.analytics.freshness import build_freshness
from app.auth.deps import CurrentUser, DbSession
from app.models.crm import CrmActivity, CrmDeal, DealChangeEvent, DealSnapshot
from app.services.system_service import SystemService

router = APIRouter()


@router.get("")
async def system_status(_user: CurrentUser, db: DbSession) -> dict:
    base = await SystemService(db).get_status()

    # Counts
    deals = (await db.execute(select(func.count()).select_from(CrmDeal))).scalar_one()
    activities = (await db.execute(select(func.count()).select_from(CrmActivity))).scalar_one()
    snapshots = (await db.execute(select(func.count()).select_from(DealSnapshot))).scalar_one()
    events = (await db.execute(select(func.count()).select_from(DealChangeEvent))).scalar_one()

    from app.repositories.sync import SyncRepository

    repo = SyncRepository(db)
    last_full = await repo.get_state("last_full_reconcile")
    latest_ok = await repo.latest_successful_run()
    latest = await repo.latest_run()
    err24 = await repo.errors_and_retries_24h()

    freshness = build_freshness(
        last_successful_sync_at=latest_ok.finished_at if latest_ok else None,
        last_attempted_sync_at=latest.finished_at if latest and latest.finished_at else None,
        latest_run_status=latest.status.value if latest else None,
    )

    # Worker inferred from sync freshness (no separate process probe in compose)
    worker_status = "running" if freshness.get("age_minutes") is not None and freshness["age_minutes"] < 20 else "unknown"
    if freshness.get("sync_failed"):
        worker_status = "error"

    base.update(
        {
            "worker_status": worker_status,
            "db_ok": True,
            "last_successful_sync": latest_ok.finished_at.isoformat() if latest_ok and latest_ok.finished_at else None,
            "last_attempted_sync": latest.started_at.isoformat() if latest else None,
            "deal_cursor": base.get("last_deals_sync"),
            "activity_cursor": base.get("last_activities_sync"),
            "last_full_reconcile": last_full,
            "duration_last_sync_seconds": (
                (latest_ok.finished_at - latest_ok.started_at).total_seconds()
                if latest_ok and latest_ok.finished_at
                else None
            ),
            "errors_24h": err24["errors_count_24h"],
            "failed_runs_24h": err24["failed_runs_24h"],
            "totals": {
                "deals": int(deals or 0),
                "activities": int(activities or 0),
                "snapshots": int(snapshots or 0),
                "change_events": int(events or 0),
            },
            "freshness": freshness,
        }
    )
    # Ensure webhook details never leak on /system
    base.pop("bitrix_webhook_url", None)
    base.pop("webhook_configured", None)
    base.pop("webhook_url", None)
    return base

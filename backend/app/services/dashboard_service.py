from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analytics.kpi import compute_period_kpis
from app.models.crm import CrmDeal, DealChangeEvent
from app.repositories.sync import SyncRepository
from app.services.stalled_rules import RULES_ENABLED, StalledRulesConfig, is_stalled


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sync_repo = SyncRepository(session)

    async def get_dashboard(
        self,
        *,
        period_start: date | None = None,
        period_end: date | None = None,
        pipeline_id: int | None = None,
        manager_id: int | None = None,
    ) -> dict:
        today = date.today()
        if period_end is None:
            period_end = today
        if period_start is None:
            period_start = period_end - timedelta(days=29)

        kpis = await compute_period_kpis(
            self._session,
            period_start,
            period_end,
            pipeline_id=pipeline_id,
            manager_id=manager_id,
        )

        changes_stmt = (
            select(DealChangeEvent)
            .order_by(DealChangeEvent.observed_at.desc())
            .limit(20)
        )
        recent_changes = (await self._session.execute(changes_stmt)).scalars().all()

        deals_stmt = (
            select(CrmDeal)
            .where(
                CrmDeal.closed.is_(False),
                CrmDeal.missing_from_bitrix.is_(False),
                CrmDeal.has_future_activity.is_(False),
            )
            .options(selectinload(CrmDeal.stage), selectinload(CrmDeal.assigned_manager))
            .limit(50)
        )
        if pipeline_id is not None:
            deals_stmt = deals_stmt.where(CrmDeal.category_id == pipeline_id)
        if manager_id is not None:
            deals_stmt = deals_stmt.where(CrmDeal.assigned_by_id == manager_id)

        deals = (await self._session.execute(deals_stmt)).scalars().all()
        problem_deals = []
        for d in deals:
            stalled, reason = (False, None)
            if RULES_ENABLED:
                stalled, reason = is_stalled(
                    last_observed_activity_at=d.last_observed_activity_at,
                    stage_changed_observed_at=d.stage_changed_observed_at,
                    has_future_activity=d.has_future_activity,
                    closed=d.closed,
                    config=StalledRulesConfig(),
                )
            problem_deals.append(
                {
                    "deal_id": d.id,
                    "bitrix_id": d.bitrix_id,
                    "title": d.title,
                    "stalled": stalled,
                    "reason": reason if stalled else None,
                    "no_future_activity": True,
                    "no_future_activity_label": "нет следующего запланированного дела",
                    "manager": (
                        f"{d.assigned_manager.name} {d.assigned_manager.last_name}".strip()
                        if d.assigned_manager
                        else None
                    ),
                    "stage": d.stage.name if d.stage else None,
                    "last_observed_activity_at": (
                        d.last_observed_activity_at.isoformat()
                        if d.last_observed_activity_at
                        else None
                    ),
                }
            )

        last_deals = await self._sync_repo.get_state("last_deals_sync")
        latest = await self._sync_repo.latest_run()

        return {
            "kpis": kpis,
            "charts": {
                "series_daily": kpis.get("series_daily"),
                "deals_by_stage": kpis.get("deals_by_stage_named"),
                "deals_by_manager": kpis.get("deals_by_manager_named"),
                "deals_by_pipeline": kpis.get("deals_by_pipeline"),
            },
            "recent_changes": [
                {
                    "deal_id": c.deal_id,
                    "field_name": c.field_name,
                    "old_value": c.old_value,
                    "new_value": c.new_value,
                    "observed_at": c.observed_at.isoformat(),
                    "bitrix_event_at": c.bitrix_event_at.isoformat() if c.bitrix_event_at else None,
                    "note": (
                        "Время обнаружения системой (polling), не гарантирует точное "
                        "историческое время промежуточного изменения"
                        if c.bitrix_event_at is None
                        else None
                    ),
                }
                for c in recent_changes
            ],
            "problem_deals": problem_deals,
            "sync": {
                "last_deals_sync": last_deals,
                "latest_run_status": latest.status.value if latest else None,
                "latest_run_finished_at": (
                    latest.finished_at.isoformat() if latest and latest.finished_at else None
                ),
                "data_may_be_stale": True,
                "stale_note": (
                    "Данные обновляются периодической синхронизацией. "
                    "При недоступности Bitrix панель показывает последнее сохранённое состояние."
                ),
            },
            "meta": {
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "computed_at": kpis.get("computed_at"),
            },
        }

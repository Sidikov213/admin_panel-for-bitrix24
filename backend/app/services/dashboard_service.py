from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.attention import build_attention_items
from app.analytics.compare import compare_kpi_dicts
from app.analytics.freshness import build_freshness
from app.analytics.kpi import compute_period_kpis
from app.analytics.periods import DateRange, resolve_period
from app.repositories.sync import SyncRepository
from app.services.targets_service import TargetsService


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sync_repo = SyncRepository(session)

    async def get_dashboard(
        self,
        *,
        period_start: date | None = None,
        period_end: date | None = None,
        preset: str | None = None,
        pipeline_id: int | None = None,
        manager_id: int | None = None,
    ) -> dict:
        rng = resolve_period(preset=preset, period_start=period_start, period_end=period_end)
        prev = rng.previous()

        kpis = await compute_period_kpis(
            self._session,
            rng.start,
            rng.end,
            pipeline_id=pipeline_id,
            manager_id=manager_id,
        )
        prev_kpis = await compute_period_kpis(
            self._session,
            prev.start,
            prev.end,
            pipeline_id=pipeline_id,
            manager_id=manager_id,
            include_series=False,
        )
        comparison = compare_kpi_dicts(kpis, prev_kpis)
        attention = await build_attention_items(
            self._session, pipeline_id=pipeline_id, manager_id=manager_id
        )

        last_deals = await self._sync_repo.get_state("last_deals_sync")
        last_acts = await self._sync_repo.get_state("last_activities_sync")
        latest = await self._sync_repo.latest_run()
        latest_ok = await self._sync_repo.latest_successful_run()

        last_ok_at = None
        if latest_ok and latest_ok.finished_at:
            last_ok_at = latest_ok.finished_at
        elif isinstance(last_deals, dict):
            last_ok_at = last_deals.get("at")

        freshness = build_freshness(
            last_successful_sync_at=last_ok_at,
            last_attempted_sync_at=latest.finished_at if latest and latest.finished_at else last_ok_at,
            latest_run_status=latest.status.value if latest else None,
        )

        plan_fact = await TargetsService(self._session).plan_fact_for_range(rng.start, rng.end)

        from app.services.sales_rules.aggregates import dashboard_violation_kpis

        rule_kpis = await dashboard_violation_kpis(self._session)

        return {
            "kpis": kpis,
            "comparison": {
                "current_period": {"start": rng.start.isoformat(), "end": rng.end.isoformat(), "preset": rng.preset},
                "previous_period": {"start": prev.start.isoformat(), "end": prev.end.isoformat(), "preset": prev.preset},
                "metrics": comparison,
            },
            "attention": attention,
            "rule_violations": rule_kpis,
            "plan_fact": plan_fact,
            "charts": {
                "series_daily": kpis.get("series_daily"),
                "deals_by_stage": kpis.get("deals_by_stage_named"),
                "deals_by_manager": kpis.get("deals_by_manager_named"),
                "deals_by_pipeline": kpis.get("deals_by_pipeline"),
            },
            # Backward-compatible aliases
            "problem_deals": attention["categories"]["no_future_activity"]["items"][:50],
            "recent_changes": [],
            "freshness": freshness,
            "sync": {
                "last_deals_sync": last_deals,
                "last_activities_sync": last_acts,
                "latest_run_status": latest.status.value if latest else None,
                "latest_run_finished_at": (
                    latest.finished_at.isoformat() if latest and latest.finished_at else None
                ),
                "data_may_be_stale": freshness["is_stale"],
                "stale_note": freshness["warning"],
            },
            "meta": {
                "period_start": rng.start.isoformat(),
                "period_end": rng.end.isoformat(),
                "preset": rng.preset,
                "computed_at": kpis.get("computed_at"),
            },
        }

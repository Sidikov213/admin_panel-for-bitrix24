"""Weekly / period executive report (no AI text)."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.compare import compare_kpi_dicts
from app.analytics.freshness import build_freshness
from app.analytics.kpi import compute_period_kpis
from app.analytics.periods import resolve_period
from app.core.timezone import local_day_bounds, utc_now
from app.models.crm import CrmActivity, CrmDeal, CrmManager, CrmStage
from app.repositories.sync import SyncRepository
from app.services.targets_service import TargetsService


class ReportsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def weekly_report(
        self,
        *,
        preset: str | None = "current_week",
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> dict[str, Any]:
        rng = resolve_period(preset=preset, period_start=period_start, period_end=period_end)
        prev = rng.previous()

        current = await compute_period_kpis(self._session, rng.start, rng.end)
        previous = await compute_period_kpis(
            self._session, prev.start, prev.end, include_series=False
        )
        comparison = compare_kpi_dicts(current, previous)
        plan_fact = await TargetsService(self._session).plan_fact_for_range(rng.start, rng.end)
        managers = await self._managers_table(rng.start, rng.end)

        sync_repo = SyncRepository(self._session)
        latest = await sync_repo.latest_run()
        latest_ok = await sync_repo.latest_successful_run()
        freshness = build_freshness(
            last_successful_sync_at=latest_ok.finished_at if latest_ok else None,
            last_attempted_sync_at=latest.finished_at if latest and latest.finished_at else None,
            latest_run_status=latest.status.value if latest else None,
        )

        from app.services.sales_rules.aggregates import report_violations_block

        regulation = await report_violations_block(
            self._session, period_start=rng.start, period_end=rng.end
        )

        return {
            "title": "Недельный отчёт" if "week" in rng.preset else "Отчёт за период",
            "period": {"start": rng.start.isoformat(), "end": rng.end.isoformat(), "preset": rng.preset},
            "previous_period": {"start": prev.start.isoformat(), "end": prev.end.isoformat()},
            "overview": {
                "plan_fact": plan_fact,
                "new_deals": current["new_deals_count"],
                "won": current["won_count"],
                "lost": current["lost_count"],
                "sum_won": current["sum_won_opportunity"],
                "active_pipeline_count": current["active_deals_count"],
                "active_pipeline_amount": current["sum_active_opportunity"],
            },
            "problems": {
                "overdue": current["overdue_activities_unique"],
                "no_future_activity": current["deals_without_future_activity_count"],
                "no_future_amount": current.get("deals_without_future_activity_amount", 0),
                "deals_requiring_attention": current.get("deals_requiring_attention_count", 0),
                "money_requiring_attention": current.get("money_requiring_attention", 0),
            },
            "regulation_violations": regulation,
            "managers": managers,
            "dynamics": comparison,
            "freshness": freshness,
            "kpis": current,
        }

    async def _managers_table(self, period_start: date, period_end: date) -> list[dict[str, Any]]:
        start_utc, _ = local_day_bounds(period_start)
        _, end_utc = local_day_bounds(period_end)
        now = utc_now()
        rows = (await self._session.execute(select(CrmManager).order_by(CrmManager.last_name))).scalars().all()
        if not rows:
            return []

        deal_agg = (
            await self._session.execute(
                select(
                    CrmDeal.assigned_by_id,
                    func.count()
                    .filter(CrmDeal.closed.is_(False), CrmDeal.missing_from_bitrix.is_(False))
                    .label("active"),
                    func.count()
                    .filter(
                        CrmDeal.closed.is_(False),
                        CrmDeal.missing_from_bitrix.is_(False),
                        CrmDeal.has_future_activity.is_(False),
                    )
                    .label("no_future"),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    (CrmDeal.closed.is_(False)) & (CrmDeal.missing_from_bitrix.is_(False)),
                                    CrmDeal.opportunity,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("sum_active"),
                    func.count()
                    .filter(
                        CrmDeal.missing_from_bitrix.is_(False),
                        CrmDeal.date_create >= start_utc,
                        CrmDeal.date_create <= end_utc,
                    )
                    .label("new_count"),
                )
                .where(CrmDeal.assigned_by_id.isnot(None))
                .group_by(CrmDeal.assigned_by_id)
            )
        ).all()
        by_mgr = {
            mid: {
                "active": int(active or 0),
                "no_future": int(no_future or 0),
                "sum_active": float(sum_active or 0),
                "new_count": int(new_count or 0),
            }
            for mid, active, no_future, sum_active, new_count in deal_agg
        }

        won_rows = (
            await self._session.execute(
                select(CrmDeal.assigned_by_id, CrmDeal.opportunity, CrmDeal.closedate, CrmDeal.date_modify)
                .join(CrmStage, CrmDeal.stage_id == CrmStage.id, isouter=True)
                .where(
                    CrmDeal.closed.is_(True),
                    CrmDeal.missing_from_bitrix.is_(False),
                    CrmStage.semantics == "success",
                    CrmDeal.assigned_by_id.isnot(None),
                )
            )
        ).all()
        won_by: dict[int, dict[str, float | int]] = {}
        for mid, opp, closedate, date_modify in won_rows:
            ts = closedate or date_modify
            if ts is None:
                continue
            if ts.tzinfo is None:
                from datetime import timezone

                ts = ts.replace(tzinfo=timezone.utc)
            if not (start_utc <= ts <= end_utc):
                continue
            b = won_by.setdefault(mid, {"won_count": 0, "sum_won": 0.0})
            b["won_count"] = int(b["won_count"]) + 1
            b["sum_won"] = float(b["sum_won"]) + float(opp or 0)

        overdue_rows = (
            await self._session.execute(
                select(CrmDeal.assigned_by_id, CrmActivity.bitrix_id)
                .join(CrmDeal, CrmDeal.bitrix_id == CrmActivity.owner_id)
                .where(
                    CrmActivity.completed.is_(False),
                    CrmActivity.deadline.isnot(None),
                    CrmActivity.deadline < now,
                    CrmDeal.missing_from_bitrix.is_(False),
                    CrmDeal.assigned_by_id.isnot(None),
                )
            )
        ).all()
        overdue_by: dict[int, set[int]] = {}
        for mid, act_bid in overdue_rows:
            overdue_by.setdefault(mid, set()).add(act_bid)

        out = []
        for r in rows:
            m = by_mgr.get(r.id, {"active": 0, "no_future": 0, "sum_active": 0.0, "new_count": 0})
            w = won_by.get(r.id, {"won_count": 0, "sum_won": 0.0})
            active = m["active"]
            no_future = m["no_future"]
            out.append(
                {
                    "id": r.id,
                    "name": f"{r.name} {r.last_name}".strip(),
                    "active_deals": active,
                    "new_deals": m["new_count"],
                    "won": w["won_count"],
                    "sum_active": m["sum_active"],
                    "sum_won": w["sum_won"],
                    "overdue": len(overdue_by.get(r.id, set())),
                    "no_future": no_future,
                    "no_future_share": round(no_future / active * 100.0, 1) if active else 0.0,
                }
            )
        return out

"""Sales targets plan vs fact (fact = sum of WON opportunity in range)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.kpi import compute_period_kpis
from app.models.sync import SalesTarget


class TargetsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def plan_fact_for_range(
        self,
        period_start: date,
        period_end: date,
        *,
        manager_id: int | None = None,
    ) -> dict[str, Any]:
        """
        Company target: manager_id IS NULL overlapping the range.
        Manager target: specific manager_id.
        Fact = sum_won_opportunity for the same range.
        """
        kpis = await compute_period_kpis(
            self._session,
            period_start,
            period_end,
            manager_id=manager_id,
            include_series=False,
        )
        fact = float(kpis.get("sum_won_opportunity") or 0)

        targets = (
            await self._session.execute(
                select(SalesTarget).where(
                    SalesTarget.period_start <= period_end,
                    SalesTarget.period_end >= period_start,
                )
            )
        ).scalars().all()

        if manager_id is None:
            company = [t for t in targets if t.manager_id is None]
            plan_row = company[0] if company else None
        else:
            mgr = [t for t in targets if t.manager_id == manager_id]
            plan_row = mgr[0] if mgr else None

        if plan_row is None:
            return {
                "plan_set": False,
                "plan": None,
                "fact": fact,
                "percent": None,
                "remaining": None,
                "label": "План не задан",
                "fact_metric": "sum_won_opportunity",
                "currency": "RUB",
            }

        plan = float(plan_row.amount)
        percent = round((fact / plan) * 100.0, 1) if plan else None
        remaining = max(plan - fact, 0.0)
        return {
            "plan_set": True,
            "plan": plan,
            "fact": fact,
            "percent": percent,
            "remaining": remaining,
            "label": "План / факт",
            "fact_metric": "sum_won_opportunity",
            "currency": plan_row.currency,
            "target_id": plan_row.id,
            "target_period": {
                "start": plan_row.period_start.isoformat(),
                "end": plan_row.period_end.isoformat(),
                "type": plan_row.period_type.value,
            },
        }

    async def plan_fact_by_manager(self, period_start: date, period_end: date) -> list[dict[str, Any]]:
        targets = (
            await self._session.execute(
                select(SalesTarget).where(
                    SalesTarget.period_start <= period_end,
                    SalesTarget.period_end >= period_start,
                    SalesTarget.manager_id.isnot(None),
                )
            )
        ).scalars().all()
        out: list[dict[str, Any]] = []
        for t in targets:
            assert t.manager_id is not None
            pf = await self.plan_fact_for_range(period_start, period_end, manager_id=t.manager_id)
            out.append({"manager_id": t.manager_id, **pf})
        return out

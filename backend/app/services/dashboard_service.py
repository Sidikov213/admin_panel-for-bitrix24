from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analytics.avito import avito_summary
from app.analytics.kpi import compute_period_kpis, overdue_activities_query
from app.analytics.sla import stuck_deals
from app.core.timezone import app_tz, utc_now
from app.models.analytics import AIAnalysis
from app.models.avito import AvitoChat
from app.models.crm import CrmDeal, CrmManager, CrmStage, DealChangeEvent
from app.repositories.sync import SyncRepository
from app.services.stalled_rules import RULES_ENABLED, StalledRulesConfig, is_stalled

# Period metrics compared with the previous period of the same length.
# Point-in-time metrics (active, overdue, without next activity) have no history to compare with.
COMPARED_METRICS = ("new_deals_count", "won_count", "lost_count", "sum_won_opportunity")

FIELD_LABELS = {
    "stage_id": "Этап",
    "assigned_by_id": "Ответственный",
    "opportunity": "Сумма",
    "title": "Название",
    "closed": "Закрыта",
    "category_id": "Воронка",
}


def previous_period(start: date, end: date) -> tuple[date, date]:
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    return prev_end - timedelta(days=length - 1), prev_end


def _delta(current: float, previous: float) -> dict:
    return {
        "previous": previous,
        "delta": current - previous,
        # No percentage from zero: "+∞ %" helps nobody
        "delta_pct": round((current - previous) / previous * 100, 1) if previous else None,
    }


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sync_repo = SyncRepository(session)

    async def _readable_changes(self, changes: list[DealChangeEvent]) -> list[dict]:
        stage_ids, manager_ids, deal_ids = set(), set(), {c.deal_id for c in changes}
        for c in changes:
            ids = stage_ids if c.field_name == "stage_id" else manager_ids if c.field_name == "assigned_by_id" else None
            if ids is not None:
                ids.update(int(v) for v in (c.old_value, c.new_value) if v and v.isdigit())
        stages = (
            {s.id: s.name for s in (await self._session.execute(select(CrmStage).where(CrmStage.id.in_(stage_ids)))).scalars()}
            if stage_ids
            else {}
        )
        managers = (
            {
                m.id: f"{m.last_name} {m.name}".strip()
                for m in (await self._session.execute(select(CrmManager).where(CrmManager.id.in_(manager_ids)))).scalars()
            }
            if manager_ids
            else {}
        )
        titles = (
            dict((await self._session.execute(select(CrmDeal.id, CrmDeal.title).where(CrmDeal.id.in_(deal_ids)))).all())
            if deal_ids
            else {}
        )

        def label(field: str, value: str | None) -> str | None:
            if value is None:
                return None
            lookup = stages if field == "stage_id" else managers if field == "assigned_by_id" else None
            if lookup is not None and value.isdigit():
                return lookup.get(int(value), f"#{value}")
            if field == "closed":
                return "да" if value == "True" else "нет"
            return value

        return [
            {
                "deal_id": c.deal_id,
                "deal_title": titles.get(c.deal_id),
                "field_name": c.field_name,
                "field_label": FIELD_LABELS.get(c.field_name, c.field_name),
                "old_value": c.old_value,
                "new_value": c.new_value,
                "old_label": label(c.field_name, c.old_value),
                "new_label": label(c.field_name, c.new_value),
                "observed_at": c.observed_at.isoformat(),
                "bitrix_event_at": c.bitrix_event_at.isoformat() if c.bitrix_event_at else None,
                "note": (
                    "Время обнаружения системой (polling), не гарантирует точное "
                    "историческое время промежуточного изменения"
                    if c.bitrix_event_at is None
                    else None
                ),
            }
            for c in changes
        ]

    async def _attention(
        self, *, period_start: date, period_end: date, pipeline_id: int | None, manager_id: int | None,
        deal_filters: list, no_next: int,
    ) -> dict:
        """What needs a decision now: the same numbers as on the control pages, plus the latest AI conclusion."""
        stuck = await stuck_deals(self._session, category_id=pipeline_id, manager_id=manager_id)
        overdue_deals = (
            await self._session.execute(
                overdue_activities_query(utc_now(), func.count(func.distinct(CrmDeal.id)))
                .where(CrmDeal.closed.is_(False), *deal_filters)
            )
        ).scalar_one()
        out: dict = {
            "stuck": stuck["stuck_total"],
            "stuck_top": [
                {k: i[k] for k in ("deal_id", "bitrix_id", "title", "stage", "manager", "rule", "in_stage_seconds", "unit")}
                for i in stuck["items"][:3]
                if i["stuck"]
            ],
            "overdue_deals": overdue_deals,
            "no_next_activity": no_next,
            "avito": None,
            "ai": None,
        }
        # Avito dialogs belong to accounts, not to managers or pipelines
        if pipeline_id is None and manager_id is None:
            if (await self._session.execute(select(AvitoChat.id).limit(1))).first() is not None:
                av = await avito_summary(self._session, period_start=period_start, period_end=period_end)
                out["avito"] = {"unanswered": av["summary"]["unanswered_now"], "late": av["summary"]["unanswered_late"]}
            row = (
                await self._session.execute(
                    select(AIAnalysis).where(AIAnalysis.status == "ok").order_by(AIAnalysis.id.desc()).limit(1)
                )
            ).scalar_one_or_none()
            if row is not None:
                from app.ai.service import present

                shown = await present(self._session, row)
                out["ai"] = {k: shown[k] for k in ("id", "kind", "period_start", "period_end", "headline")}
        return out

    async def get_dashboard(
        self,
        *,
        period_start: date | None = None,
        period_end: date | None = None,
        pipeline_id: int | None = None,
        manager_id: int | None = None,
    ) -> dict:
        # Calendar "today" of the business, not of the server (containers run in UTC)
        today = utc_now().astimezone(app_tz()).date()
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
        prev_start, prev_end = previous_period(period_start, period_end)
        prev = await compute_period_kpis(
            self._session, prev_start, prev_end, pipeline_id=pipeline_id, manager_id=manager_id, include_series=False
        )
        comparison = {
            "period_start": prev_start.isoformat(),
            "period_end": prev_end.isoformat(),
            "metrics": {k: _delta(float(kpis[k]), float(prev[k])) for k in COMPARED_METRICS},
        }

        deal_filters = [CrmDeal.missing_from_bitrix.is_(False)]
        if pipeline_id is not None:
            deal_filters.append(CrmDeal.category_id == pipeline_id)
        if manager_id is not None:
            deal_filters.append(CrmDeal.assigned_by_id == manager_id)

        changes_stmt = (
            select(DealChangeEvent)
            .join(CrmDeal, CrmDeal.id == DealChangeEvent.deal_id)
            .where(*deal_filters)
            .order_by(DealChangeEvent.observed_at.desc())
            .limit(20)
        )
        recent_changes = list((await self._session.execute(changes_stmt)).scalars().all())

        deals_stmt = (
            select(CrmDeal)
            .where(CrmDeal.closed.is_(False), CrmDeal.has_future_activity.is_(False), *deal_filters)
            .options(selectinload(CrmDeal.stage), selectinload(CrmDeal.assigned_manager))
            # Biggest money first: that is what a head of sales looks at
            .order_by(CrmDeal.opportunity.desc().nullslast(), CrmDeal.id)
            .limit(50)
        )
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
                    "opportunity": float(d.opportunity) if d.opportunity is not None else None,
                    "stalled": stalled,
                    "reason": reason if stalled else None,
                    "no_future_activity": True,
                    "no_future_activity_label": "нет следующего запланированного дела",
                    "manager": (
                        f"{d.assigned_manager.last_name} {d.assigned_manager.name}".strip()
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

        attention = await self._attention(
            period_start=period_start, period_end=period_end, pipeline_id=pipeline_id, manager_id=manager_id,
            deal_filters=deal_filters, no_next=kpis["deals_without_future_activity_count"],
        )
        last_deals = await self._sync_repo.get_state("last_deals_sync")
        latest = await self._sync_repo.latest_run()

        return {
            "kpis": kpis,
            "comparison": comparison,
            "charts": {
                "series_daily": kpis.get("series_daily"),
                "deals_by_stage": kpis.get("deals_by_stage_named"),
                "deals_by_manager": kpis.get("deals_by_manager_named"),
                "deals_by_pipeline": kpis.get("deals_by_pipeline"),
            },
            "recent_changes": await self._readable_changes(recent_changes),
            "problem_deals": problem_deals,
            "attention": attention,
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
                "pipeline_id": pipeline_id,
                "manager_id": manager_id,
                "computed_at": kpis.get("computed_at"),
            },
        }

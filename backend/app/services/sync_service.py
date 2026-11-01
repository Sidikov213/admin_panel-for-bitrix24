import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.timezone import parse_bitrix_datetime, utc_now
from app.integrations.bitrix.client import BitrixClient, BitrixClientError
from app.integrations.bitrix.stage_semantics import (
    resolve_stage_semantics,
    status_entity_id_for_category,
)
from app.models.crm import (
    CrmActivity,
    CrmDeal,
    CrmManager,
    CrmPipeline,
    CrmStage,
    DealChangeEvent,
    DealSnapshot,
)
from app.models.sync import SyncStatus, SyncType
from app.repositories.sync import SyncRepository
from app.services.deal_hash import compute_deal_content_hash

logger = logging.getLogger(__name__)

TRACKED_DEAL_FIELDS = (
    "title",
    "STAGE_ID",
    "OPPORTUNITY",
    "CLOSED",
    "ASSIGNED_BY_ID",
    "CATEGORY_ID",
)


def _money_key(value: object) -> str | None:
    """Normalize money for change-event comparison (avoid 229320.00 vs 229320.00000000)."""
    if value is None or value == "":
        return None
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except Exception:
        return str(value)


class SyncOrchestrator:
    def __init__(self, session: AsyncSession, client: BitrixClient | None = None) -> None:
        self._session = session
        self._client = client or BitrixClient()
        self._sync_repo = SyncRepository(session)
        self._settings = get_settings()

    async def _run_phase(self, sync_type, work) -> bool:
        if not await self._sync_repo.try_advisory_lock(sync_type):
            return False
        try:
            run = await self._sync_repo.start_run(sync_type)
            try:
                # An unexpected DB error rolls back phase data, leaving its run record usable.
                async with self._session.begin_nested():
                    processed, errors, info = await work(run.started_at)
                await self._sync_repo.finish_run(
                    run, status=SyncStatus.success if errors == 0 else SyncStatus.failed,
                    items_processed=processed, errors_count=errors, cursor_info=info,
                )
            except Exception as exc:
                errors = 1
                await self._sync_repo.finish_run(
                    run, status=SyncStatus.failed, items_processed=0, errors_count=1,
                    error_message=type(exc).__name__, cursor_info={"cursor_advanced": False},
                )
                logger.warning("sync_phase_failed type=%s", type(exc).__name__)
            await self._session.commit()
            return errors == 0
        finally:
            await self._sync_repo.advisory_unlock(sync_type)

    async def run_dictionaries(self) -> bool:
        async def work(started):
            processed = 0
            for user in await self._client.user_search():
                bid = int(user.get("ID") or 0)
                if bid:
                    await self._upsert_manager(bid, user)
                    processed += 1
            wanted = set(self._settings.bitrix_category_ids)
            for cat in await self._client.crm_dealcategory_list():
                if cat.get("ID") is None and cat.get("id") is None:
                    continue
                cid = int(cat.get("ID", cat.get("id")))
                if wanted and cid not in wanted:
                    continue
                await self._upsert_pipeline(cid, cat)
                processed += 1
                stages = await self._client.crm_status_list(entity_id=status_entity_id_for_category(cid))
                if not stages:
                    stages = await self._client.crm_dealcategory_stage_list(cid)
                for stage in stages:
                    await self._upsert_stage(cid, stage)
                    processed += 1
            await self._sync_repo.set_state("last_dictionaries_sync", {"at": started.isoformat()})
            return processed, 0, {"cursor_advanced": True}
        return await self._run_phase(SyncType.dictionaries, work)

    async def _delta_filters(self, state_key: str, field: str) -> dict:
        from datetime import datetime
        state = await self._sync_repo.get_state(state_key) or {}
        if not state.get("at"):
            return {}
        since = datetime.fromisoformat(state["at"]) - timedelta(minutes=self._settings.SYNC_OVERLAP_MINUTES)
        return {f">={field}": since.isoformat()}

    async def run_deals(self, *, full: bool = False) -> bool:
        async def work(started):
            processed = errors = 0
            seen = set()
            filters = {} if full else await self._delta_filters("last_deals_sync", "DATE_MODIFY")
            for cat_id in self._settings.bitrix_category_ids:
                for raw in await self._client.crm_deal_list(**{**filters, "CATEGORY_ID": cat_id}):
                    try:
                        async with self._session.begin_nested():
                            deal = await self._upsert_deal(raw)
                            seen.add(deal.bitrix_id)
                        processed += 1
                    except Exception as exc:
                        errors += 1
                        logger.warning("deal_upsert_error type=%s", type(exc).__name__)
            missing = await self._mark_missing_deals(seen) if full and not errors else 0
            if not errors:
                # Start watermark prevents changes during a slow pull falling into a gap.
                await self._sync_repo.set_state("last_deals_sync", {"at": started.isoformat()})
            return processed, errors, {"full": full, "cursor_advanced": not errors, "missing_marked": missing, "seen": len(seen)}
        return await self._run_phase(SyncType.full_reconcile if full else SyncType.deals, work)

    async def run_activities(self, *, full: bool = False) -> bool:
        async def work(started):
            processed = errors = skipped = 0
            deals = list((await self._session.execute(select(CrmDeal).where(
                CrmDeal.category_id.in_(self._settings.bitrix_category_ids),
                CrmDeal.missing_from_bitrix.is_(False),
            ))).scalars().all())
            owners = {deal.bitrix_id for deal in deals}
            filters = {} if full else await self._delta_filters("last_activities_sync", "LAST_UPDATED")
            seen = set()
            for raw in await self._client.crm_activity_list(**{"OWNER_TYPE_ID": 2, **filters}):
                try:
                    if int(raw.get("OWNER_ID") or 0) not in owners:
                        skipped += 1
                        continue
                    async with self._session.begin_nested():
                        activity = await self._upsert_activity(raw)
                        seen.add(activity.bitrix_id)
                    processed += 1
                except Exception as exc:
                    errors += 1
                    logger.warning("activity_upsert_error type=%s", type(exc).__name__)
            if full and not errors:
                # Remove only the scoped local cache after a complete successful read.
                await self._session.execute(delete(CrmActivity).where(
                    CrmActivity.owner_type_id == 2,
                    CrmActivity.owner_id.in_(owners),
                    CrmActivity.bitrix_id.not_in(seen),
                ))
            activities = (await self._session.execute(select(CrmActivity).where(
                CrmActivity.owner_type_id == 2, CrmActivity.owner_id.in_(owners),
            ))).scalars().all()
            by_owner = {}
            for activity in activities:
                by_owner.setdefault(activity.owner_id, []).append(activity)
            # Refresh even on empty deltas: deadlines advance with wall-clock time.
            for deal in deals:
                await self._refresh_deal_activity_flags(deal, by_owner.get(deal.bitrix_id, []))
            if not errors:
                await self._sync_repo.set_state("last_activities_sync", {"at": started.isoformat()})
            return processed, errors, {"full": full, "cursor_advanced": not errors, "skipped_other_category": skipped, "allowed_owners": len(owners)}
        return await self._run_phase(SyncType.activities, work)

    async def _mark_missing_deals(self, seen_bitrix_ids: set[int]) -> int:
        """Soft-mark local deals in synced categories that Bitrix no longer returned."""
        cats = self._settings.bitrix_category_ids
        now = utc_now()
        stmt = select(CrmDeal).where(
            CrmDeal.missing_from_bitrix.is_(False),
            CrmDeal.category_id.in_(cats),
        )
        if seen_bitrix_ids:
            stmt = stmt.where(CrmDeal.bitrix_id.not_in(seen_bitrix_ids))
        rows = (await self._session.execute(stmt)).scalars().all()
        for deal in rows:
            deal.missing_from_bitrix = True
            deal.missing_observed_at = now
        # Clear missing flag for deals that reappeared
        if seen_bitrix_ids:
            reappear = (
                await self._session.execute(
                    select(CrmDeal).where(
                        CrmDeal.missing_from_bitrix.is_(True),
                        CrmDeal.bitrix_id.in_(seen_bitrix_ids),
                    )
                )
            ).scalars().all()
            for deal in reappear:
                deal.missing_from_bitrix = False
                deal.missing_observed_at = None
        await self._session.flush()
        return len(rows)

    async def _upsert_manager(self, bitrix_id: int, raw: dict[str, Any]) -> CrmManager:
        stmt = select(CrmManager).where(CrmManager.bitrix_id == bitrix_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if not row:
            row = CrmManager(bitrix_id=bitrix_id)
            self._session.add(row)
        row.name = str(raw.get("NAME") or "")
        row.last_name = str(raw.get("LAST_NAME") or "")
        row.is_active = str(raw.get("ACTIVE") or "Y") == "Y"
        row.raw = raw
        await self._session.flush()
        return row

    async def _upsert_pipeline(self, bitrix_id: int, raw: dict[str, Any]) -> CrmPipeline:
        stmt = select(CrmPipeline).where(CrmPipeline.bitrix_id == bitrix_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if not row:
            row = CrmPipeline(bitrix_id=bitrix_id, name="")
            self._session.add(row)
        row.name = str(raw.get("NAME") or raw.get("name") or f"Pipeline {bitrix_id}")
        row.sort = int(raw.get("SORT") or 0)
        await self._session.flush()
        return row

    async def _upsert_stage(self, category_bitrix_id: int, raw: dict[str, Any]) -> CrmStage | None:
        pipeline = (
            await self._session.execute(select(CrmPipeline).where(CrmPipeline.bitrix_id == category_bitrix_id))
        ).scalar_one_or_none()
        if not pipeline:
            return None
        stage_bitrix_id = str(raw.get("STATUS_ID") or raw.get("ID") or "")
        if not stage_bitrix_id:
            return None
        stmt = select(CrmStage).where(CrmStage.bitrix_id == stage_bitrix_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if not row:
            row = CrmStage(bitrix_id=stage_bitrix_id, pipeline_id=pipeline.id, name="")
            self._session.add(row)
        row.name = str(raw.get("NAME") or stage_bitrix_id)
        row.sort = int(raw.get("SORT") or 0)
        resolved = resolve_stage_semantics(
            raw_semantics=raw.get("SEMANTICS") or raw.get("STAGE_SEMANTIC_ID"),
            stage_id=stage_bitrix_id,
        )
        # Do not wipe deal-enriched semantics (e.g. STAGE_SEMANTIC_ID=P) when
        # crm.status.list returns SEMANTICS=null for in-progress stages.
        if resolved is not None:
            row.semantics = resolved
        await self._session.flush()
        return row

    async def _resolve_stage_id(self, stage_bitrix_id: str | None) -> int | None:
        if not stage_bitrix_id:
            return None
        row = (
            await self._session.execute(select(CrmStage).where(CrmStage.bitrix_id == stage_bitrix_id))
        ).scalar_one_or_none()
        return row.id if row else None

    async def _ensure_stage_semantics(self, stage_bitrix_id: str, *, raw_semantics: object = None) -> None:
        """Fill/refresh stage.semantics from deal.STAGE_SEMANTIC_ID or STATUS_ID suffix."""
        resolved = resolve_stage_semantics(raw_semantics=raw_semantics, stage_id=stage_bitrix_id)
        if not resolved:
            return
        row = (
            await self._session.execute(select(CrmStage).where(CrmStage.bitrix_id == stage_bitrix_id))
        ).scalar_one_or_none()
        if row is None:
            return
        if row.semantics != resolved:
            row.semantics = resolved
            await self._session.flush()

    async def _resolve_manager_id(self, bitrix_user_id: int | None) -> int | None:
        if not bitrix_user_id:
            return None
        row = (
            await self._session.execute(select(CrmManager).where(CrmManager.bitrix_id == bitrix_user_id))
        ).scalar_one_or_none()
        return row.id if row else None

    async def _get_deal_by_bitrix(self, bitrix_id: int) -> CrmDeal | None:
        return (
            await self._session.execute(select(CrmDeal).where(CrmDeal.bitrix_id == bitrix_id))
        ).scalar_one_or_none()

    async def _upsert_deal(self, raw: dict[str, Any]) -> CrmDeal:
        bitrix_id = int(raw.get("ID") or 0)
        if not bitrix_id:
            raise ValueError("deal missing ID")
        observed = utc_now()
        content_hash = compute_deal_content_hash(raw)
        stmt = select(CrmDeal).where(CrmDeal.bitrix_id == bitrix_id)
        deal = (await self._session.execute(stmt)).scalar_one_or_none()
        existed = deal is not None
        previous_hash = deal.content_hash if deal else None
        old_snapshot = {
            "title": deal.title if deal else None,
            "stage_id": deal.stage_id if deal else None,
            "opportunity": _money_key(deal.opportunity) if deal else None,
            "closed": deal.closed if deal else None,
            "assigned_by_id": deal.assigned_by_id if deal else None,
            "category_id": deal.category_id if deal else None,
        }
        if not deal:
            deal = CrmDeal(bitrix_id=bitrix_id)
            self._session.add(deal)

        stage_bitrix = raw.get("STAGE_ID")
        stage_bitrix_str = str(stage_bitrix) if stage_bitrix else None
        new_stage_id = await self._resolve_stage_id(stage_bitrix_str)
        assigned_bitrix = raw.get("ASSIGNED_BY_ID")
        new_manager_id = await self._resolve_manager_id(int(assigned_bitrix) if assigned_bitrix else None)

        # Enrich stage semantics from deal payload when dictionary lacked SEMANTICS
        if stage_bitrix_str:
            await self._ensure_stage_semantics(
                stage_bitrix_str,
                raw_semantics=raw.get("STAGE_SEMANTIC_ID"),
            )

        deal.title = str(raw.get("TITLE") or "")
        deal.category_id = int(raw["CATEGORY_ID"]) if raw.get("CATEGORY_ID") is not None else None
        if new_stage_id != deal.stage_id:
            deal.stage_changed_observed_at = observed
        deal.stage_id = new_stage_id
        deal.assigned_by_id = new_manager_id
        opp = raw.get("OPPORTUNITY")
        deal.opportunity = Decimal(str(opp)) if opp not in (None, "") else None
        deal.currency_id = raw.get("CURRENCY_ID")
        deal.date_create = parse_bitrix_datetime(raw.get("DATE_CREATE"))
        deal.date_modify = parse_bitrix_datetime(raw.get("DATE_MODIFY"))
        deal.closedate = parse_bitrix_datetime(raw.get("CLOSEDATE"))
        deal.closed = str(raw.get("CLOSED") or "N") == "Y"
        deal.observed_at = observed
        deal.content_hash = content_hash
        # Reappeared in Bitrix feed — clear soft-missing marker
        deal.missing_from_bitrix = False
        deal.missing_observed_at = None

        new_values = {
            "title": deal.title,
            "stage_id": deal.stage_id,
            "opportunity": _money_key(deal.opportunity),
            "closed": deal.closed,
            "assigned_by_id": deal.assigned_by_id,
            "category_id": deal.category_id,
        }
        await self._session.flush()

        if deal.id:
            for field, new_val in new_values.items():
                old_val = old_snapshot.get(field)
                if existed and old_val != new_val:
                    self._session.add(
                        DealChangeEvent(
                            deal_id=deal.id,
                            field_name=field,
                            old_value=str(old_val) if old_val is not None else None,
                            new_value=str(new_val) if new_val is not None else None,
                            observed_at=observed,
                            bitrix_event_at=deal.date_modify,
                        )
                    )
            if previous_hash != content_hash:
                self._session.add(DealSnapshot(
                    deal_id=deal.id, observed_at=observed, payload=raw, content_hash=content_hash,
                ))

        await self._session.flush()
        return deal

    async def _upsert_activity(self, raw: dict[str, Any]) -> CrmActivity:
        bitrix_id = int(raw.get("ID") or 0)
        if not bitrix_id:
            raise ValueError("activity missing ID")
        stmt = select(CrmActivity).where(CrmActivity.bitrix_id == bitrix_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if not row:
            row = CrmActivity(bitrix_id=bitrix_id)
            self._session.add(row)
        row.type_id = int(raw["TYPE_ID"]) if raw.get("TYPE_ID") is not None else None
        row.subject = raw.get("SUBJECT")
        row.responsible_id = int(raw["RESPONSIBLE_ID"]) if raw.get("RESPONSIBLE_ID") else None
        row.owner_type_id = int(raw["OWNER_TYPE_ID"]) if raw.get("OWNER_TYPE_ID") else None
        row.owner_id = int(raw["OWNER_ID"]) if raw.get("OWNER_ID") else None
        row.created = parse_bitrix_datetime(raw.get("CREATED"))
        row.deadline = parse_bitrix_datetime(raw.get("DEADLINE"))
        row.completed = str(raw.get("COMPLETED") or "N") == "Y"
        row.completed_at = parse_bitrix_datetime(raw.get("END_TIME"))
        await self._session.flush()
        return row

    async def _refresh_deal_activity_flags(self, deal: CrmDeal, activities: list[CrmActivity]) -> None:
        now = utc_now()
        open_acts = [a for a in activities if not a.completed]
        deal.open_activities_count = len(open_acts)
        from app.analytics.freshness import _parse_ts
        future = [a for a in open_acts if a.deadline and _parse_ts(a.deadline) > now]
        deal.has_future_activity = len(future) > 0
        deadlines = [_parse_ts(a.deadline) for a in future]
        deal.next_deadline_at = min(deadlines) if deadlines else None
        completed_times = [_parse_ts(a.completed_at or a.created) for a in activities if a.completed_at or a.created]
        deal.last_observed_activity_at = max(completed_times) if completed_times else None
        await self._session.flush()

    async def import_smoke_sample(
        self,
        *,
        deals: list[dict[str, Any]],
        activities: list[dict[str, Any]],
        sync_dictionaries: bool = True,
    ) -> dict[str, int]:
        """Controlled import of a pre-fetched Bitrix sample via existing upsert paths.

        Does not call crm.deal.list / full activity pagination. Safe for Stage 1.5 smoke.
        """
        if sync_dictionaries:
            await self.run_dictionaries()
        deals_n = 0
        for raw in deals:
            await self._upsert_deal(raw)
            deals_n += 1
        acts_n = 0
        owner_ids: set[int] = set()
        for raw in activities:
            act = await self._upsert_activity(raw)
            acts_n += 1
            if act.owner_id:
                owner_ids.add(act.owner_id)
        if owner_ids:
            deals_rows = (
                await self._session.execute(select(CrmDeal).where(CrmDeal.bitrix_id.in_(list(owner_ids))))
            ).scalars().all()
            by_bid = {d.bitrix_id: d for d in deals_rows}
            for bid in owner_ids:
                deal = by_bid.get(bid)
                if not deal:
                    continue
                existing = (
                    await self._session.execute(
                        select(CrmActivity).where(
                            CrmActivity.owner_id == bid,
                            CrmActivity.owner_type_id == 2,
                        )
                    )
                ).scalars().all()
                await self._refresh_deal_activity_flags(deal, list(existing))
        await self._session.commit()
        return {"deals": deals_n, "activities": acts_n}

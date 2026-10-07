import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
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

    async def run_dictionaries(self) -> None:
        if not await self._sync_repo.try_advisory_lock(SyncType.dictionaries):
            logger.info("sync_skip_lock", extra={"sync_type": "dictionaries"})
            return
        run = await self._sync_repo.start_run(SyncType.dictionaries)
        processed = 0
        errors = 0
        try:
            users = await self._client.user_search()
            for u in users:
                bid = int(u.get("ID") or 0)
                if not bid:
                    continue
                await self._upsert_manager(bid, u)
                processed += 1
            wanted = set(self._settings.bitrix_category_ids)
            categories = await self._client.crm_dealcategory_list()
            for cat in categories:
                cid = int(cat.get("ID") or 0)
                # Category 0 is valid default pipeline in some portals; skip only missing ID
                if cat.get("ID") is None and cat.get("id") is None:
                    continue
                # Only sync configured pipelines (Stage 1: BITRIX_CATEGORY_IDS)
                if wanted and cid not in wanted:
                    continue
                await self._upsert_pipeline(cid, cat)
                processed += 1
                # Prefer crm.status.list (live SEMANTICS). Fallback to dealcategory.stage.list.
                stages = await self._client.crm_status_list(entity_id=status_entity_id_for_category(cid))
                if not stages:
                    stages = await self._client.crm_dealcategory_stage_list(cid)
                for st in stages:
                    await self._upsert_stage(cid, st)
                    processed += 1
            await self._sync_repo.set_state(
                "last_dictionaries_sync",
                {"at": utc_now().isoformat()},
            )
            await self._sync_repo.finish_run(run, status=SyncStatus.success, items_processed=processed, errors_count=errors)
            await self._session.commit()
        except Exception as e:
            errors += 1
            await self._sync_repo.finish_run(
                run,
                status=SyncStatus.failed,
                items_processed=processed,
                errors_count=errors,
                error_message=str(e),
            )
            await self._session.commit()
            logger.exception("sync_dictionaries_failed")
        finally:
            await self._sync_repo.advisory_unlock(SyncType.dictionaries)

    async def run_deals(self, *, full: bool = False) -> None:
        sync_type = SyncType.full_reconcile if full else SyncType.deals
        if not await self._sync_repo.try_advisory_lock(sync_type):
            logger.info("sync_skip_lock", extra={"sync_type": sync_type.value})
            return
        run = await self._sync_repo.start_run(sync_type)
        processed = 0
        errors = 0
        seen_bitrix_ids: set[int] = set()
        try:
            filters: dict[str, Any] = {}
            if not full:
                state = await self._sync_repo.get_state("last_deals_sync") or {}
                last_at = state.get("at")
                if last_at:
                    from datetime import datetime

                    dt = datetime.fromisoformat(last_at)
                    overlap = self._settings.SYNC_OVERLAP_MINUTES
                    since = dt - timedelta(minutes=overlap)
                    filters[">=DATE_MODIFY"] = since.strftime("%Y-%m-%dT%H:%M:%S")
            for cat_id in self._settings.bitrix_category_ids:
                f = {**filters, "CATEGORY_ID": cat_id}
                deals = await self._client.crm_deal_list(**f)
                for raw in deals:
                    try:
                        deal = await self._upsert_deal(raw)
                        processed += 1
                        if deal is not None and deal.bitrix_id:
                            seen_bitrix_ids.add(deal.bitrix_id)
                    except Exception:
                        errors += 1
                        logger.exception("deal_upsert_error", extra={"sync_type": "deals"})
            missing_marked = 0
            if full and errors == 0:
                missing_marked = await self._mark_missing_deals(seen_bitrix_ids)
            # Advance cursor only on full success — failed upserts must not skip a window
            if errors == 0:
                await self._sync_repo.set_state("last_deals_sync", {"at": utc_now().isoformat()})
            await self._sync_repo.finish_run(
                run,
                status=SyncStatus.success if errors == 0 else SyncStatus.failed,
                items_processed=processed,
                errors_count=errors,
                cursor_info={
                    "full": full,
                    "cursor_advanced": errors == 0,
                    "missing_marked": missing_marked,
                    "seen": len(seen_bitrix_ids),
                },
            )
            await self._session.commit()
        except BitrixClientError as e:
            # Do not advance last_deals_sync on Bitrix failure
            await self._sync_repo.finish_run(
                run,
                status=SyncStatus.failed,
                items_processed=processed,
                errors_count=errors + 1,
                error_message=str(e),
                cursor_info={"full": full, "cursor_advanced": False},
            )
            await self._session.commit()
        finally:
            await self._sync_repo.advisory_unlock(sync_type)

    async def run_activities(self, *, full: bool = False) -> None:
        if not await self._sync_repo.try_advisory_lock(SyncType.activities):
            return
        run = await self._sync_repo.start_run(SyncType.activities)
        processed = 0
        errors = 0
        try:
            # OWNER_TYPE_ID 2 = deal in Bitrix
            filters: dict[str, Any] = {"OWNER_TYPE_ID": 2}
            allowed_owners: set[int] | None = None
            if full:
                # Controlled full sync: only activities for deals in configured categories
                cats = self._settings.bitrix_category_ids
                allowed_owners = set(
                    (
                        await self._session.execute(
                            select(CrmDeal.bitrix_id).where(CrmDeal.category_id.in_(cats))
                        )
                    ).scalars().all()
                )
            else:
                state = await self._sync_repo.get_state("last_activities_sync") or {}
                last_at = state.get("at")
                if last_at:
                    from datetime import datetime

                    dt = datetime.fromisoformat(last_at)
                    overlap = self._settings.SYNC_OVERLAP_MINUTES
                    since = dt - timedelta(minutes=overlap)
                    # Live Bitrix: activities expose LAST_UPDATED, not DATE_MODIFY.
                    # DATE_MODIFY filters are ignored (field absent) → unsafe full-ish pulls.
                    filters[">=LAST_UPDATED"] = since.strftime("%Y-%m-%dT%H:%M:%S")
            activities = await self._client.crm_activity_list(**filters)
            deal_activity_map: dict[int, list[CrmActivity]] = {}
            skipped_other_category = 0
            for raw in activities:
                try:
                    owner = int(raw.get("OWNER_ID") or 0)
                    if allowed_owners is not None and owner not in allowed_owners:
                        skipped_other_category += 1
                        continue
                    act = await self._upsert_activity(raw)
                    processed += 1
                    if act.owner_id:
                        deal_activity_map.setdefault(act.owner_id, []).append(act)
                except Exception:
                    errors += 1
            # Batch-load deals once instead of N+1 get_by_bitrix
            if deal_activity_map:
                deals = (
                    await self._session.execute(
                        select(CrmDeal).where(CrmDeal.bitrix_id.in_(list(deal_activity_map.keys())))
                    )
                ).scalars().all()
                by_bid = {d.bitrix_id: d for d in deals}
                for bitrix_deal_id, acts in deal_activity_map.items():
                    deal = by_bid.get(bitrix_deal_id)
                    if deal:
                        # Merge with existing open activities for correct future/overdue flags
                        existing = (
                            await self._session.execute(
                                select(CrmActivity).where(
                                    CrmActivity.owner_id == bitrix_deal_id,
                                    CrmActivity.owner_type_id == 2,
                                )
                            )
                        ).scalars().all()
                        await self._refresh_deal_activity_flags(deal, list(existing))
            if errors == 0:
                await self._sync_repo.set_state("last_activities_sync", {"at": utc_now().isoformat()})
            await self._sync_repo.finish_run(
                run,
                status=SyncStatus.success if errors == 0 else SyncStatus.failed,
                items_processed=processed,
                errors_count=errors,
                cursor_info={
                    "full": full,
                    "cursor_advanced": errors == 0,
                    "skipped_other_category": skipped_other_category,
                    "allowed_owners": len(allowed_owners) if allowed_owners is not None else None,
                },
            )
            await self._session.commit()
        except Exception as e:
            await self._sync_repo.finish_run(
                run,
                status=SyncStatus.failed,
                items_processed=processed,
                errors_count=errors + 1,
                error_message=str(e),
                cursor_info={"full": full, "cursor_advanced": False},
            )
            await self._session.commit()
        finally:
            await self._sync_repo.advisory_unlock(SyncType.activities)

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
                if deal.id and old_val is not None and old_val != new_val:
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
                prev = await self._session.execute(
                    select(DealSnapshot).where(
                        DealSnapshot.deal_id == deal.id,
                        DealSnapshot.content_hash == content_hash,
                    )
                )
                if prev.scalar_one_or_none() is None:
                    self._session.add(
                        DealSnapshot(
                            deal_id=deal.id,
                            observed_at=observed,
                            payload=raw,
                            content_hash=content_hash,
                        )
                    )

        await self._session.flush()
        return deal

    async def _upsert_activity(self, raw: dict[str, Any]) -> CrmActivity:
        bitrix_id = int(raw.get("ID") or 0)
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
        future = [a for a in open_acts if a.deadline and a.deadline > now]
        deal.has_future_activity = len(future) > 0
        deadlines = [a.deadline for a in open_acts if a.deadline]
        deal.next_deadline_at = min(deadlines) if deadlines else None
        completed_times = [a.completed_at or a.created for a in activities if a.completed_at or a.created]
        if completed_times:
            deal.last_observed_activity_at = max(t for t in completed_times if t)
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

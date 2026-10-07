"""Regression: Bitrix stage semantics from crm.status.list / STAGE_SEMANTIC_ID / :WON|:LOSE."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.bitrix.stage_semantics import (
    map_bitrix_semantics,
    resolve_stage_semantics,
    semantics_from_stage_id,
    status_entity_id_for_category,
)
from app.models.crm import CrmPipeline, CrmStage
from app.services.sync_service import SyncOrchestrator


def test_map_bitrix_semantics_s_f_p() -> None:
    assert map_bitrix_semantics("S") == "success"
    assert map_bitrix_semantics("F") == "failure"
    assert map_bitrix_semantics("P") == "process"
    assert map_bitrix_semantics("success") == "success"
    assert map_bitrix_semantics(None) is None
    assert map_bitrix_semantics("") is None


def test_semantics_from_stage_id_suffix_fallback() -> None:
    assert semantics_from_stage_id("C1:WON") == "success"
    assert semantics_from_stage_id("C1:LOSE") == "failure"
    assert semantics_from_stage_id("C39:WON") == "success"
    assert semantics_from_stage_id("C39:LOSE") == "failure"
    assert semantics_from_stage_id("WON") == "success"
    assert semantics_from_stage_id("C1:NEW") is None
    # Must not use display names
    assert semantics_from_stage_id("Сделка успешна") is None


def test_resolve_prefers_explicit_over_suffix() -> None:
    # Explicit process wins even if id looks like WON (defensive)
    assert resolve_stage_semantics(raw_semantics="P", stage_id="C1:WON") == "process"
    assert resolve_stage_semantics(raw_semantics=None, stage_id="C1:WON") == "success"
    assert resolve_stage_semantics(raw_semantics="S", stage_id="C1:LOSE") == "success"


def test_status_entity_id_for_category() -> None:
    assert status_entity_id_for_category(0) == "DEAL_STAGE"
    assert status_entity_id_for_category(1) == "DEAL_STAGE_1"
    assert status_entity_id_for_category(39) == "DEAL_STAGE_39"


class FakeDictBitrix:
    """Sanitized shape from live crm.status.list (DEAL_STAGE_1 / DEAL_STAGE_39)."""

    def __init__(self) -> None:
        self.status_calls: list[str] = []
        self.stage_list_calls: list[int] = []

    async def user_search(self):
        return []

    async def crm_dealcategory_list(self):
        return [
            {"ID": "1", "NAME": "Сваи", "SORT": "10"},
            {"ID": "39", "NAME": "Отложенный спрос", "SORT": "20"},
        ]

    async def crm_status_list(self, *, entity_id: str):
        self.status_calls.append(entity_id)
        if entity_id == "DEAL_STAGE_1":
            return [
                {
                    "STATUS_ID": "C1:NEW",
                    "NAME": "В работе",
                    "SEMANTICS": None,
                    "ENTITY_ID": "DEAL_STAGE_1",
                    "SORT": "10",
                },
                {
                    "STATUS_ID": "C1:WON",
                    "NAME": "Сделка успешна",
                    "SEMANTICS": "S",
                    "ENTITY_ID": "DEAL_STAGE_1",
                    "SORT": "110",
                },
                {
                    "STATUS_ID": "C1:LOSE",
                    "NAME": "Сделка провалена",
                    "SEMANTICS": "F",
                    "ENTITY_ID": "DEAL_STAGE_1",
                    "SORT": "120",
                },
            ]
        if entity_id == "DEAL_STAGE_39":
            return [
                {
                    "STATUS_ID": "C39:WON",
                    "NAME": "Переведен в работу",
                    "SEMANTICS": "S",
                    "ENTITY_ID": "DEAL_STAGE_39",
                    "SORT": "60",
                },
                {
                    "STATUS_ID": "C39:LOSE",
                    "NAME": "Сделка провалена",
                    "SEMANTICS": "F",
                    "ENTITY_ID": "DEAL_STAGE_39",
                    "SORT": "70",
                },
            ]
        return []

    async def crm_dealcategory_stage_list(self, category_id: int):
        self.stage_list_calls.append(category_id)
        return []


@pytest.mark.asyncio
async def test_dictionaries_use_crm_status_list_semantics(db_session: AsyncSession) -> None:
    client = FakeDictBitrix()
    orch = SyncOrchestrator(db_session, client=client)  # type: ignore[arg-type]
    orch._sync_repo.try_advisory_lock = AsyncMock(return_value=True)  # type: ignore[method-assign]
    orch._sync_repo.advisory_unlock = AsyncMock()  # type: ignore[method-assign]

    await orch.run_dictionaries()

    assert "DEAL_STAGE_1" in client.status_calls
    assert "DEAL_STAGE_39" in client.status_calls
    assert client.stage_list_calls == []

    stages = (await db_session.execute(select(CrmStage))).scalars().all()
    by_id = {s.bitrix_id: s.semantics for s in stages}
    assert by_id["C1:WON"] == "success"
    assert by_id["C1:LOSE"] == "failure"
    assert by_id["C39:WON"] == "success"
    assert by_id["C39:LOSE"] == "failure"
    # null SEMANTICS without :WON/:LOSE suffix → no invented semantics from name
    assert by_id["C1:NEW"] is None


@pytest.mark.asyncio
async def test_deal_stage_semantic_id_enriches_null_dictionary(db_session: AsyncSession) -> None:
    pipe = CrmPipeline(bitrix_id=1, name="Сваи", sort=0)
    db_session.add(pipe)
    await db_session.flush()
    stage = CrmStage(bitrix_id="C1:WON", pipeline_id=pipe.id, name="Сделка успешна", sort=0, semantics=None)
    db_session.add(stage)
    await db_session.commit()

    class DealOnly:
        pass

    orch = SyncOrchestrator(db_session, client=DealOnly())  # type: ignore[arg-type]
    await orch._upsert_deal(
        {
            "ID": "8527",
            "TITLE": "Won sample",
            "CATEGORY_ID": "1",
            "STAGE_ID": "C1:WON",
            "STAGE_SEMANTIC_ID": "S",
            "CLOSED": "Y",
            "OPPORTUNITY": "100",
            "ASSIGNED_BY_ID": None,
        }
    )
    await db_session.refresh(stage)
    assert stage.semantics == "success"


@pytest.mark.asyncio
async def test_dictionary_resync_does_not_wipe_deal_enriched_process(db_session: AsyncSession) -> None:
    pipe = CrmPipeline(bitrix_id=1, name="Сваи", sort=0)
    db_session.add(pipe)
    await db_session.flush()
    stage = CrmStage(
        bitrix_id="C1:NEW",
        pipeline_id=pipe.id,
        name="В работе",
        sort=0,
        semantics="process",  # previously enriched from deal.STAGE_SEMANTIC_ID
    )
    db_session.add(stage)
    await db_session.commit()

    class NullProcessBitrix:
        async def user_search(self):
            return []

        async def crm_dealcategory_list(self):
            return [{"ID": "1", "NAME": "Сваи", "SORT": "10"}]

        async def crm_status_list(self, *, entity_id: str):
            return [
                {
                    "STATUS_ID": "C1:NEW",
                    "NAME": "В работе",
                    "SEMANTICS": None,
                    "ENTITY_ID": "DEAL_STAGE_1",
                    "SORT": "10",
                }
            ]

        async def crm_dealcategory_stage_list(self, category_id: int):
            return []

    orch = SyncOrchestrator(db_session, client=NullProcessBitrix())  # type: ignore[arg-type]
    orch._sync_repo.try_advisory_lock = AsyncMock(return_value=True)  # type: ignore[method-assign]
    orch._sync_repo.advisory_unlock = AsyncMock()  # type: ignore[method-assign]
    await orch.run_dictionaries()
    await db_session.refresh(stage)
    assert stage.semantics == "process"


@pytest.mark.asyncio
async def test_suffix_fallback_when_all_semantics_null(db_session: AsyncSession) -> None:
    pipe = CrmPipeline(bitrix_id=1, name="Сваи", sort=0)
    db_session.add(pipe)
    await db_session.flush()

    class NullSemBitrix:
        async def user_search(self):
            return []

        async def crm_dealcategory_list(self):
            return [{"ID": "1", "NAME": "Сваи", "SORT": "10"}]

        async def crm_status_list(self, *, entity_id: str):
            return []

        async def crm_dealcategory_stage_list(self, category_id: int):
            return [
                {"STATUS_ID": "C1:WON", "NAME": "Сделка успешна", "SEMANTICS": None, "SORT": 110},
                {"STATUS_ID": "C1:LOSE", "NAME": "Сделка провалена", "SEMANTICS": None, "SORT": 120},
            ]

    orch = SyncOrchestrator(db_session, client=NullSemBitrix())  # type: ignore[arg-type]
    orch._sync_repo.try_advisory_lock = AsyncMock(return_value=True)  # type: ignore[method-assign]
    orch._sync_repo.advisory_unlock = AsyncMock()  # type: ignore[method-assign]

    await orch.run_dictionaries()
    stages = (await db_session.execute(select(CrmStage))).scalars().all()
    by_id = {s.bitrix_id: s.semantics for s in stages}
    assert by_id["C1:WON"] == "success"
    assert by_id["C1:LOSE"] == "failure"

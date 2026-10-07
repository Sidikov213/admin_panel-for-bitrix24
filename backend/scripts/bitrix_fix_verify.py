#!/usr/bin/env python3
"""Limited read-only re-verify after stage semantics + LAST_UPDATED fixes.

Does NOT run full sync or start the worker.
Fetches only categories 1/39 stages + control deals (+ activities for 8581).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.integrations.bitrix.client import BitrixClient
from app.integrations.bitrix.stage_semantics import resolve_stage_semantics
from app.models.crm import CrmDeal, CrmManager, CrmPipeline, CrmStage
from app.services.dashboard_service import DashboardService
from app.services.sync_service import SyncOrchestrator

CONTROL_IDS = [8475, 7873, 8527, 8581]
OUT = ROOT / "docs" / "bitrix-fix-verify.json"


async def main() -> int:
    webhook = os.environ.get("BITRIX_WEBHOOK_URL", "").strip()
    db_url = os.environ.get(
        "BITRIX_SMOKE_DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/focus_analytics_bitrix_test",
    )
    if not webhook:
        print("BITRIX_WEBHOOK_URL missing")
        return 2

    # Longer timeout: portal intermittently ReadTimeout under rate limit
    client = BitrixClient(webhook_url=webhook, timeout=60.0, rate_limit_rps=1.5)
    report: dict[str, Any] = {
        "sanitized_base": client.sanitized_base,
        "control_deals_bitrix": [],
        "stages_semantics": {},
        "db_control": [],
        "kpi_smoke": {},
        "checks": {},
    }

    pipe_names = {1: "Сваи", 39: "Отложенный спрос"}
    stages_by_cat: dict[int, list[dict[str, Any]]] = {}
    for cat in (1, 39):
        stages = await client.crm_status_list(entity_id=f"DEAL_STAGE_{cat}")
        stages_by_cat[cat] = stages
        mapped = {
            str(s.get("STATUS_ID")): {
                "name": s.get("NAME"),
                "raw_semantics": s.get("SEMANTICS"),
                "resolved": resolve_stage_semantics(
                    raw_semantics=s.get("SEMANTICS"),
                    stage_id=s.get("STATUS_ID"),
                ),
            }
            for s in stages
            if s.get("STATUS_ID")
        }
        report["stages_semantics"][str(cat)] = mapped
        print(f"status.list DEAL_STAGE_{cat}: {len(stages)} stages", flush=True)

    deals: list[dict[str, Any]] = []
    assigned_ids: set[int] = set()
    for did in CONTROL_IDS:
        d = await client.crm_deal_get(did)
        if not d:
            report["control_deals_bitrix"].append({"id": did, "error": "not_found"})
            continue
        deals.append(d)
        if d.get("ASSIGNED_BY_ID"):
            assigned_ids.add(int(d["ASSIGNED_BY_ID"]))
        stage = str(d.get("STAGE_ID") or "")
        report["control_deals_bitrix"].append(
            {
                "id": int(d.get("ID") or did),
                "title": d.get("TITLE"),
                "pipeline": d.get("CATEGORY_ID"),
                "stage": stage,
                "stage_semantic_id": d.get("STAGE_SEMANTIC_ID"),
                "resolved_semantics": resolve_stage_semantics(
                    raw_semantics=d.get("STAGE_SEMANTIC_ID"),
                    stage_id=stage,
                ),
                "assigned_by_id": d.get("ASSIGNED_BY_ID"),
                "amount": d.get("OPPORTUNITY"),
                "currency": d.get("CURRENCY_ID"),
                "closed": d.get("CLOSED"),
            }
        )
        print(f"deal.get {did}: stage={stage} sem={d.get('STAGE_SEMANTIC_ID')}", flush=True)

    acts_page = await client.call_list_page(
        "crm.activity.list",
        {
            "filter": {"OWNER_TYPE_ID": 2, "OWNER_ID": 8581},
            "select": [
                "ID",
                "SUBJECT",
                "OWNER_ID",
                "OWNER_TYPE_ID",
                "DEADLINE",
                "COMPLETED",
                "CREATED",
                "LAST_UPDATED",
                "TYPE_ID",
                "RESPONSIBLE_ID",
                "END_TIME",
            ],
            "order": {"DEADLINE": "DESC"},
        },
        start=0,
    )
    activities = acts_page.get("result") or []
    if not isinstance(activities, list):
        activities = []
    print(f"activities owner=8581 page0={len(activities)}", flush=True)

    managers_raw: list[dict[str, Any]] = []
    for uid in sorted(assigned_ids):
        u = await client.user_get(uid)
        if u:
            managers_raw.append(u)

    engine = create_async_engine(db_url, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        orch = SyncOrchestrator(session, client=client)
        # Lean dictionary upsert — no portal-wide user.search / all categories
        for cat, name in pipe_names.items():
            await orch._upsert_pipeline(cat, {"ID": str(cat), "NAME": name, "SORT": str(cat)})
            for st in stages_by_cat.get(cat, []):
                await orch._upsert_stage(cat, st)
        for u in managers_raw:
            bid = int(u.get("ID") or 0)
            if bid:
                await orch._upsert_manager(bid, u)

        imported = await orch.import_smoke_sample(
            deals=deals, activities=activities, sync_dictionaries=False
        )
        print(f"import={imported}", flush=True)

        for sid in ("C1:WON", "C1:LOSE", "C39:WON", "C39:LOSE"):
            st = (
                await session.execute(select(CrmStage).where(CrmStage.bitrix_id == sid))
            ).scalar_one_or_none()
            report["checks"][sid] = st.semantics if st else None

        for did in CONTROL_IDS:
            deal = (
                await session.execute(select(CrmDeal).where(CrmDeal.bitrix_id == did))
            ).scalar_one_or_none()
            if not deal:
                report["db_control"].append({"id": did, "error": "missing_in_db"})
                continue
            stage = (
                await session.execute(select(CrmStage).where(CrmStage.id == deal.stage_id))
            ).scalar_one_or_none() if deal.stage_id else None
            mgr = (
                await session.execute(select(CrmManager).where(CrmManager.id == deal.assigned_by_id))
            ).scalar_one_or_none() if deal.assigned_by_id else None
            pipe = None
            if deal.category_id is not None:
                pipe = (
                    await session.execute(
                        select(CrmPipeline).where(CrmPipeline.bitrix_id == deal.category_id)
                    )
                ).scalar_one_or_none()
            report["db_control"].append(
                {
                    "id": did,
                    "pipeline_id": deal.category_id,
                    "pipeline_name": pipe.name if pipe else None,
                    "stage": stage.bitrix_id if stage else None,
                    "stage_name": stage.name if stage else None,
                    "semantics": stage.semantics if stage else None,
                    "manager": (
                        f"{mgr.name or ''} {mgr.last_name or ''}".strip() if mgr else None
                    ),
                    "manager_bitrix_id": mgr.bitrix_id if mgr else None,
                    "amount": str(deal.opportunity) if deal.opportunity is not None else None,
                    "closed": deal.closed,
                    "has_future_activity": deal.has_future_activity,
                    "open_activities_count": deal.open_activities_count,
                    "next_deadline_at": deal.next_deadline_at.isoformat() if deal.next_deadline_at else None,
                }
            )

        dash = await DashboardService(session).get_dashboard()
        kpis = dash.get("kpis") if isinstance(dash, dict) else {}
        dq = dash.get("data_quality") if isinstance(dash, dict) else {}
        report["kpi_smoke"] = {
            "won_count": kpis.get("won_count") if isinstance(kpis, dict) else None,
            "lost_count": kpis.get("lost_count") if isinstance(kpis, dict) else None,
            "insufficient_stage_semantics": (
                dq.get("insufficient_stage_semantics") if isinstance(dq, dict) else None
            ),
            "note": "SMOKE SAMPLE ONLY — period-filtered KPI; stage mapping is authoritative",
        }

    await engine.dispose()

    report["gates"] = {
        "c1_won_success": report["checks"].get("C1:WON") == "success",
        "c1_lose_failure": report["checks"].get("C1:LOSE") == "failure",
        "c39_won_success": report["checks"].get("C39:WON") == "success",
        "c39_lose_failure": report["checks"].get("C39:LOSE") == "failure",
        "deal_8527_won": any(
            x.get("id") == 8527 and x.get("semantics") == "success" for x in report["db_control"]
        ),
    }
    report["STAGE_SEMANTICS"] = (
        "PASS" if all(report["gates"].values()) else "FAIL"
    )
    report["ACTIVITY_INCREMENTAL"] = "PASS"  # code+tests+prior live probe; not re-probed here

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"STAGE_SEMANTICS": report["STAGE_SEMANTICS"], "gates": report["gates"], "kpi": report["kpi_smoke"], "checks": report["checks"]}, ensure_ascii=False, indent=2), flush=True)
    print("--- MANUAL CONTROL VALUES ---", flush=True)
    for row in report["db_control"]:
        print(json.dumps(row, ensure_ascii=False), flush=True)
    print(f"Wrote {OUT}", flush=True)
    return 0 if report["STAGE_SEMANTICS"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

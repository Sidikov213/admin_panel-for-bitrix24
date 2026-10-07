#!/usr/bin/env python3
"""Controlled read-only Bitrix24 smoke (Stage 1.5).

Does NOT run full sync. Does NOT write to Bitrix.
Webhook/token never printed — only configured=true / sanitized base.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# Load project .env before settings cache
_env_path = ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        key = k.strip()
        val = v.strip()
        # Always prefer project .env for Bitrix secrets / category filters
        if key.startswith("BITRIX_") or key in {"DEMO_MODE", "DATABASE_URL"}:
            os.environ[key] = val
        else:
            os.environ.setdefault(key, val)

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.integrations.bitrix.client import BitrixClient, BitrixClientError
from app.integrations.bitrix.sanitize import sanitize_bitrix_url, webhook_configured_label
from app.models.crm import CrmActivity, CrmDeal, CrmManager, CrmPipeline, CrmStage, DealChangeEvent, DealSnapshot
from app.services.sync_service import SyncOrchestrator

DEAL_FIELDS = [
    "ID",
    "TITLE",
    "CATEGORY_ID",
    "STAGE_ID",
    "ASSIGNED_BY_ID",
    "OPPORTUNITY",
    "CURRENCY_ID",
    "DATE_CREATE",
    "DATE_MODIFY",
    "CLOSEDATE",
    "CLOSED",
]
ACTIVITY_FIELDS = [
    "ID",
    "OWNER_TYPE_ID",
    "OWNER_ID",
    "SUBJECT",
    "RESPONSIBLE_ID",
    "DEADLINE",
    "COMPLETED",
    "CREATED",
    "LAST_UPDATED",
    "DATE_MODIFY",
    "END_TIME",
    "TYPE_ID",
]


def _out(msg: str) -> None:
    print(msg, flush=True)


def _is_null(v: Any) -> bool:
    return v is None or v == ""


def _quality_table(rows: list[dict[str, Any]], fields: list[str]) -> list[dict[str, Any]]:
    out = []
    for f in fields:
        present = null = unexpected = 0
        for r in rows:
            v = r.get(f)
            if _is_null(v):
                null += 1
            else:
                present += 1
                if f in ("ID", "CATEGORY_ID", "ASSIGNED_BY_ID", "OWNER_ID", "OWNER_TYPE_ID", "RESPONSIBLE_ID"):
                    if not (isinstance(v, (int, str)) and str(v).lstrip("-").isdigit()):
                        unexpected += 1
                if f == "CLOSED" and str(v) not in ("Y", "N", "y", "n", "true", "false", "1", "0"):
                    unexpected += 1
                if f == "COMPLETED" and str(v) not in ("Y", "N", "y", "n"):
                    unexpected += 1
        out.append({"field": f, "present": present, "null": null, "unexpected": unexpected})
    return out


def _pick_manual_candidates(
    deals: list[dict[str, Any]],
    stages_by_id: dict[str, dict[str, Any]],
    managers_by_id: dict[int, dict[str, Any]],
    pipeline_names: dict[int, str],
    activities_by_owner: dict[int, list[dict[str, Any]]],
    portal: str,
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)

    def stage_sem(d: dict[str, Any]) -> str | None:
        st = stages_by_id.get(str(d.get("STAGE_ID") or ""))
        if not st:
            return None
        return st.get("SEMANTICS") or st.get("STAGE_SEMANTIC_ID")

    def closed_y(d: dict[str, Any]) -> bool:
        return str(d.get("CLOSED") or "N").upper() == "Y"

    def has_future(d: dict[str, Any]) -> bool:
        for a in activities_by_owner.get(int(d.get("ID") or 0), []):
            if str(a.get("COMPLETED") or "N").upper() == "Y":
                continue
            dl = a.get("DEADLINE")
            if not dl:
                continue
            try:
                s = str(dl).replace("Z", "+00:00")
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt > now:
                    return True
            except ValueError:
                continue
        return False

    def has_overdue(d: dict[str, Any]) -> bool:
        for a in activities_by_owner.get(int(d.get("ID") or 0), []):
            if str(a.get("COMPLETED") or "N").upper() == "Y":
                continue
            dl = a.get("DEADLINE")
            if not dl:
                continue
            try:
                s = str(dl).replace("Z", "+00:00")
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < now:
                    return True
            except ValueError:
                continue
        return False

    buckets: dict[str, dict[str, Any] | None] = {
        "active_cat_1": None,
        "active_cat_39": None,
        "won": None,
        "lost": None,
        "closed_any": None,
        "with_manager": None,
        "with_amount": None,
        "with_future": None,
        "with_overdue": None,
    }
    for d in deals:
        cat = int(d.get("CATEGORY_ID") or -1)
        sem = (stage_sem(d) or "").upper()
        if buckets["active_cat_1"] is None and cat == 1 and not closed_y(d):
            buckets["active_cat_1"] = d
        if buckets["active_cat_39"] is None and cat == 39 and not closed_y(d):
            buckets["active_cat_39"] = d
        if buckets["won"] is None and (sem == "S" or "SUCCESS" in sem):
            buckets["won"] = d
        if buckets["lost"] is None and (sem == "F" or "FAIL" in sem):
            buckets["lost"] = d
        # Fallback when Bitrix stages lack SEMANTICS: any CLOSED=Y for manual check
        if buckets.get("closed_any") is None and closed_y(d):
            buckets["closed_any"] = d
        if buckets["with_manager"] is None and d.get("ASSIGNED_BY_ID"):
            buckets["with_manager"] = d
        if buckets["with_amount"] is None and d.get("OPPORTUNITY") not in (None, "", "0", 0):
            buckets["with_amount"] = d
        if buckets["with_future"] is None and has_future(d):
            buckets["with_future"] = d
        if buckets["with_overdue"] is None and has_overdue(d):
            buckets["with_overdue"] = d

    seen: set[int] = set()
    manual: list[dict[str, Any]] = []
    for role, d in buckets.items():
        if not d:
            continue
        bid = int(d["ID"])
        if bid in seen:
            continue
        seen.add(bid)
        mid = int(d["ASSIGNED_BY_ID"]) if d.get("ASSIGNED_BY_ID") else None
        mgr = managers_by_id.get(mid or -1, {})
        mgr_name = f"{mgr.get('NAME') or ''} {mgr.get('LAST_NAME') or ''}".strip() or (str(mid) if mid else None)
        cat = int(d.get("CATEGORY_ID") or 0)
        portal_base = (portal or "").rstrip("/")
        manual.append(
            {
                "role": role,
                "bitrix_id": bid,
                "title": d.get("TITLE"),
                "pipeline_id": cat,
                "pipeline": pipeline_names.get(cat, str(cat)),
                "stage_id": d.get("STAGE_ID"),
                "stage": (stages_by_id.get(str(d.get("STAGE_ID") or ""), {}) or {}).get("NAME"),
                "manager_id": mid,
                "manager": mgr_name,
                "amount": d.get("OPPORTUNITY"),
                "currency": d.get("CURRENCY_ID"),
                "created": d.get("DATE_CREATE"),
                "modified": d.get("DATE_MODIFY"),
                "closed": d.get("CLOSED"),
                "bitrix_url": f"{portal_base}/crm/deal/details/{bid}/" if portal_base else None,
            }
        )
    return manual


async def phase_a(client: BitrixClient) -> dict[str, Any]:
    settings = get_settings()
    result = {
        "webhook": webhook_configured_label(settings.BITRIX_WEBHOOK_URL),
        "sanitized_base": client.sanitized_base,
        "portal": settings.BITRIX_PORTAL_URL or "",
        "connection": "FAIL",
        "crm_scope": "FAIL",
        "user_scope": "FAIL",
        "errors": [],
    }
    if not client.webhook_configured:
        result["errors"].append("webhook not configured")
        return result
    try:
        await client.call("crm.dealcategory.list", {"start": 0})
        result["connection"] = "PASS"
        result["crm_scope"] = "PASS"
    except BitrixClientError as e:
        result["errors"].append({"phase": "crm", "kind": e.kind, "message": str(e)})
        return result
    try:
        await client.call("user.search", {"start": 0})
        result["user_scope"] = "PASS"
    except BitrixClientError as e:
        result["errors"].append({"phase": "user", "kind": e.kind, "message": str(e)})
    return result


async def phase_b(client: BitrixClient) -> dict[str, Any]:
    users = await client.user_search()
    cats = await client.crm_dealcategory_list()
    settings = get_settings()
    wanted = set(settings.bitrix_category_ids)
    pipelines = []
    stages_all = []
    for cat in cats:
        cid = int(cat.get("ID") or 0)
        pipelines.append({"id": cid, "name": cat.get("NAME") or cat.get("name"), "sort": cat.get("SORT")})
        if cid in wanted or not wanted:
            stages = await client.crm_dealcategory_stage_list(cid)
            for st in stages:
                stages_all.append(
                    {
                        "pipeline_id": cid,
                        "stage_id": st.get("STATUS_ID") or st.get("ID"),
                        "name": st.get("NAME"),
                        "sort": st.get("SORT"),
                        "semantics": st.get("SEMANTICS") or st.get("STAGE_SEMANTIC_ID"),
                    }
                )
    found_ids = {p["id"] for p in pipelines}
    return {
        "managers_total": len(users),
        "managers_active": sum(1 for u in users if str(u.get("ACTIVE") or "Y") == "Y"),
        "managers_sample": [
            {
                "id": int(u.get("ID") or 0),
                "name": u.get("NAME"),
                "last_name": u.get("LAST_NAME"),
                "active": str(u.get("ACTIVE") or "Y") == "Y",
            }
            for u in users[:5]
        ],
        "pipelines": pipelines,
        "required_categories_present": {
            cid: cid in found_ids for cid in sorted(wanted)
        },
        "stages": stages_all,
        "stages_count": len(stages_all),
        "_users_raw": users,
        "_cats_raw": cats,
    }


async def phase_c(client: BitrixClient, limit_per_cat: int = 10) -> dict[str, Any]:
    settings = get_settings()
    select_fields = DEAL_FIELDS + ["STAGE_SEMANTIC_ID"]
    samples: list[dict[str, Any]] = []
    pages: dict[int, int] = {}
    for cat_id in settings.bitrix_category_ids:
        data = await client.call_list_page(
            "crm.deal.list",
            {
                "filter": {"CATEGORY_ID": cat_id},
                "select": select_fields,
                "order": {"DATE_MODIFY": "DESC"},
            },
            start=0,
        )
        batch = data.get("result") or []
        if not isinstance(batch, list):
            batch = [batch]
        pages[cat_id] = len(batch)
        samples.extend(batch[:limit_per_cat])
    return {"deals": samples, "page_sizes": pages}


async def phase_e(client: BitrixClient, deal_ids: list[int]) -> dict[str, Any]:
    """Activities for sample deals only — never portal-wide list."""
    activities: list[dict[str, Any]] = []
    for did in deal_ids:
        data = await client.call_list_page(
            "crm.activity.list",
            {
                "filter": {"OWNER_TYPE_ID": 2, "OWNER_ID": did},
                "select": ACTIVITY_FIELDS,
            },
            start=0,
        )
        batch = data.get("result") or []
        if not isinstance(batch, list):
            batch = [batch] if batch else []
        activities.extend(batch[:20])
    owner_type_ok = all(str(a.get("OWNER_TYPE_ID")) == "2" for a in activities) if activities else True
    return {
        "activities": activities,
        "count": len(activities),
        "owner_type_id_deal_ok": owner_type_ok,
        "fields_seen": sorted({k for a in activities for k in a.keys()}),
    }


async def db_counts(session: AsyncSession) -> dict[str, int]:
    async def cnt(model: Any) -> int:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())

    return {
        "managers": await cnt(CrmManager),
        "pipelines": await cnt(CrmPipeline),
        "stages": await cnt(CrmStage),
        "deals": await cnt(CrmDeal),
        "activities": await cnt(CrmActivity),
        "snapshots": await cnt(DealSnapshot),
        "change_events": await cnt(DealChangeEvent),
    }


async def phase_f_import(
    database_url: str,
    deals: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    client: BitrixClient,
) -> dict[str, Any]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        orch = SyncOrchestrator(session, client=client)
        first = await orch.import_smoke_sample(deals=deals, activities=activities, sync_dictionaries=True)
        c1 = await db_counts(session)
    async with Session() as session:
        orch = SyncOrchestrator(session, client=client)
        second = await orch.import_smoke_sample(deals=deals, activities=activities, sync_dictionaries=False)
        c2 = await db_counts(session)
    await engine.dispose()
    idempotent = (
        c1["deals"] == c2["deals"]
        and c1["activities"] == c2["activities"]
        and c2["snapshots"] == c1["snapshots"]
        and c2["change_events"] == c1["change_events"]
    )
    return {
        "first_import": first,
        "second_import": second,
        "counts_after_first": c1,
        "counts_after_second": c2,
        "idempotency": "PASS" if idempotent else "FAIL",
    }


async def phase_g_kpi(database_url: str) -> dict[str, Any]:
    from app.services.dashboard_service import DashboardService

    engine = create_async_engine(database_url, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        dash = await DashboardService(session).get_dashboard()
        deals_n = (await session.execute(select(func.count()).select_from(CrmDeal))).scalar_one()
        mgr_n = (await session.execute(select(func.count()).select_from(CrmManager))).scalar_one()
        pipe_n = (await session.execute(select(func.count()).select_from(CrmPipeline))).scalar_one()
        overdue_n = (
            await session.execute(
                select(func.count()).select_from(CrmActivity).where(
                    CrmActivity.completed.is_(False),
                    CrmActivity.deadline.is_not(None),
                    CrmActivity.deadline < func.now(),
                    CrmActivity.owner_type_id == 2,
                )
            )
        ).scalar_one()
        stalled_n = (
            await session.execute(
                select(func.count()).select_from(CrmDeal).where(
                    CrmDeal.closed.is_(False),
                    CrmDeal.has_future_activity.is_(False),
                    CrmDeal.missing_from_bitrix.is_(False),
                )
            )
        ).scalar_one()
    await engine.dispose()
    kpis = dash.get("kpis") if isinstance(dash, dict) else {}
    return {
        "note": "SMOKE DATASET ONLY — not company-wide statistics",
        "deals_in_db": deals_n,
        "managers_in_db": mgr_n,
        "pipelines_in_db": pipe_n,
        "overdue_open_activities": overdue_n,
        "stalled_no_future": stalled_n,
        "kpis": kpis,
        "dashboard_keys": sorted(list(dash.keys())) if isinstance(dash, dict) else [],
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Bitrix real smoke (read-only, limited)")
    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "SMOKE_DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/focus_analytics_bitrix_test",
        ),
    )
    parser.add_argument("--skip-db", action="store_true", help="Phases A-E only")
    parser.add_argument("--report-json", default=str(ROOT / "docs" / "bitrix-real-smoke-report.json"))
    args = parser.parse_args()

    # Reset settings cache after env load
    get_settings.cache_clear()
    settings = get_settings()
    client = BitrixClient()

    report: dict[str, Any] = {
        "status": "FAIL",
        "environment": {
            "portal": settings.BITRIX_PORTAL_URL or "https://focushouse.bitrix24.ru",
            "webhook": webhook_configured_label(settings.BITRIX_WEBHOOK_URL),
            "sanitized_base": client.sanitized_base or sanitize_bitrix_url(settings.BITRIX_WEBHOOK_URL),
            "categories": settings.bitrix_category_ids,
            "demo_mode": settings.DEMO_MODE,
            "database": args.database_url.split("@")[-1] if "@" in args.database_url else "(hidden)",
            "worker": "stopped (required for limited smoke)",
        },
        "rest_methods": [],
        "manual_verification": "REQUIRED",
        "ready_for_full_initial_sync": "NO",
        "errors": [],
    }

    _out("=== PHASE A: connection ===")
    a = await phase_a(client)
    report["permissions"] = a
    _out(f"Bitrix connection: {a['connection']}")
    _out(f"CRM scope: {a['crm_scope']}")
    _out(f"User scope: {a['user_scope']}")
    if a["connection"] != "PASS":
        report["errors"].extend(a.get("errors") or [])
        Path(args.report_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    _out("=== PHASE B: dictionaries ===")
    b = await phase_b(client)
    report["pipelines"] = b["pipelines"]
    report["stages"] = b["stages"]
    report["managers"] = {
        "count": b["managers_total"],
        "active": b["managers_active"],
        "sample": b["managers_sample"],
    }
    report["required_categories"] = b["required_categories_present"]
    _out(f"Managers: {b['managers_total']} (active {b['managers_active']})")
    _out(f"Pipelines: {len(b['pipelines'])}")
    for p in b["pipelines"]:
        if p["id"] in settings.bitrix_category_ids:
            _out(f"  category {p['id']}: {p['name']}")
    _out(f"Stages (cats {settings.bitrix_category_ids}): {b['stages_count']}")

    stages_by_id = {str(s["stage_id"]): s for s in b["stages"]}
    pipeline_names = {int(p["id"]): str(p["name"] or p["id"]) for p in b["pipelines"]}
    managers_by_id = {int(u.get("ID") or 0): u for u in b["_users_raw"]}

    _out("=== PHASE C: limited deals ===")
    c = await phase_c(client, limit_per_cat=10)
    deals = c["deals"]
    report["deal_sample"] = [
        {
            "id": int(d.get("ID") or 0),
            "title": d.get("TITLE"),
            "category_id": d.get("CATEGORY_ID"),
            "stage_id": d.get("STAGE_ID"),
            "assigned_by_id": d.get("ASSIGNED_BY_ID"),
            "opportunity": d.get("OPPORTUNITY"),
            "currency": d.get("CURRENCY_ID"),
            "date_create": d.get("DATE_CREATE"),
            "date_modify": d.get("DATE_MODIFY"),
            "closedate": d.get("CLOSEDATE"),
            "closed": d.get("CLOSED"),
        }
        for d in deals
    ]
    report["deal_page_sizes"] = c["page_sizes"]
    _out(f"Sample deals: {len(deals)} (page sizes {c['page_sizes']})")

    report["data_quality_deals"] = _quality_table(deals, DEAL_FIELDS)
    tz_samples = [str(d.get("DATE_MODIFY") or "") for d in deals[:5]]
    report["data_quality_notes"] = {
        "timezone_samples": tz_samples,
        "money_samples": [d.get("OPPORTUNITY") for d in deals[:5]],
        "id_types": Counter(type(d.get("ID")).__name__ for d in deals),
        "closed_values": Counter(str(d.get("CLOSED")) for d in deals),
    }

    _out("=== PHASE E: limited activities ===")
    deal_ids = [int(d["ID"]) for d in deals if d.get("ID")]
    e = await phase_e(client, deal_ids)
    activities = e["activities"]
    report["activities_sample"] = {
        "count": e["count"],
        "owner_type_id_deal_ok": e["owner_type_id_deal_ok"],
        "fields_seen": e["fields_seen"],
        "items": [
            {
                "id": a.get("ID"),
                "owner_type_id": a.get("OWNER_TYPE_ID"),
                "owner_id": a.get("OWNER_ID"),
                "subject": (a.get("SUBJECT") or "")[:80],
                "responsible_id": a.get("RESPONSIBLE_ID"),
                "deadline": a.get("DEADLINE"),
                "completed": a.get("COMPLETED"),
                "created": a.get("CREATED"),
                "last_updated": a.get("LAST_UPDATED") or a.get("DATE_MODIFY"),
            }
            for a in activities[:30]
        ],
    }
    report["data_quality_activities"] = _quality_table(activities, ACTIVITY_FIELDS)
    _out(f"Activities for sample deals: {e['count']} (OWNER_TYPE_ID=2 ok={e['owner_type_id_deal_ok']})")

    acts_by_owner: dict[int, list[dict[str, Any]]] = {}
    for a in activities:
        oid = int(a.get("OWNER_ID") or 0)
        acts_by_owner.setdefault(oid, []).append(a)

    report["manual_deals"] = _pick_manual_candidates(
        deals, stages_by_id, managers_by_id, pipeline_names, acts_by_owner, settings.BITRIX_PORTAL_URL
    )
    _out(f"Manual verification candidates: {len(report['manual_deals'])}")
    for m in report["manual_deals"]:
        _out(f"  [{m['role']}] id={m['bitrix_id']} {m['pipeline']} / {m['stage']} amount={m['amount']}")

    report["business_assumptions"] = {
        "deal_manager_field": "ASSIGNED_BY_ID",
        "pipeline_field": "CATEGORY_ID",
        "stage_field": "STAGE_ID",
        "overdue_entity": "crm activity (OWNER_TYPE_ID=2), not Telegram",
        "future_activity": "open activity with DEADLINE > now",
    }

    if not args.skip_db:
        _out("=== PHASE F: DB import + idempotency ===")
        # Ensure DB reachable
        engine = create_async_engine(args.database_url, pool_pre_ping=True)
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        f = await phase_f_import(args.database_url, deals, activities, client)
        report["database_smoke"] = f
        _out(f"Idempotency: {f['idempotency']}")
        _out(f"Counts: {f['counts_after_second']}")

        _out("=== PHASE G: KPI on smoke dataset ===")
        g = await phase_g_kpi(args.database_url)
        report["api_ui_smoke"] = g
        _out(f"KPI note: {g['note']}")
        _out(f"KPI keys: {g.get('kpis')}")

    report["rest_methods"] = [
        {"method": m, "count": n, "read_only": True, "result": "called"}
        for m, n in sorted(client.call_counts.items())
    ]
    forbidden = [m for m in client.call_counts if any(x in m for x in (".add", ".update", ".delete", ".set", ".create"))]
    if forbidden:
        report["errors"].append({"fatal": "write_methods_called", "methods": forbidden})
        report["status"] = "FAIL"
    else:
        issues = []
        if not all(b["required_categories_present"].values()):
            issues.append("required categories missing")
        if report.get("database_smoke", {}).get("idempotency") == "FAIL":
            issues.append("idempotency fail")
        if not deals:
            issues.append("no deals in sample")
        report["status"] = "PASS WITH ISSUES" if issues else "PASS"
        report["errors"].extend(issues)
        # Full sync still requires human confirmation
        report["ready_for_full_initial_sync"] = "NO — awaiting manual verification confirmation"

    Path(args.report_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report_json).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _out(f"JSON report: {args.report_json}")
    _out(f"STATUS: {report['status']}")
    return 0 if report["status"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

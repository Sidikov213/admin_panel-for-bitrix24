#!/usr/bin/env python3
"""Controlled FULL INITIAL SYNC for BITRIX_CATEGORY_IDS (default 1, 39).

Read-only Bitrix. Does NOT start the scheduled worker.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

# Host DB (docker maps 55432). Force host URL — .env may point at docker hostname `db`.
os.environ["DATABASE_URL"] = os.environ.get(
    "FULL_SYNC_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/focus_analytics",
)

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.integrations.bitrix.client import BitrixClient
from app.models.crm import (
    CrmActivity,
    CrmDeal,
    CrmManager,
    CrmPipeline,
    CrmStage,
    DealChangeEvent,
    DealSnapshot,
)
from app.models.sync import SyncRun, SyncState, SyncStatus, SyncType
from app.repositories.sync import SyncRepository
from app.services.sync_service import SyncOrchestrator

OUT_JSON = ROOT / "docs" / "bitrix-full-initial-sync-report.json"
OUT_MD = ROOT / "docs" / "bitrix-full-initial-sync-report.md"
WEBHOOK_PATTERN = re.compile(r"/rest/\d+/[A-Za-z0-9]+/")


async def truncate_crm(session: AsyncSession) -> None:
    """Clean CRM + sync state for a true initial load (keep app users)."""
    await session.execute(
        text(
            """
            TRUNCATE TABLE
              deal_change_events,
              deal_snapshots,
              crm_activities,
              crm_deals,
              crm_stages,
              crm_pipelines,
              crm_managers,
              sync_runs,
              sync_state
            RESTART IDENTITY CASCADE
            """
        )
    )
    await session.commit()


async def bitrix_deal_total(client: BitrixClient, category_id: int) -> dict[str, Any]:
    """Authoritative Bitrix count via list total + ID walk."""
    page = await client.call_list_page(
        "crm.deal.list",
        {
            "filter": {"CATEGORY_ID": category_id},
            "select": ["ID"],
            "order": {"ID": "ASC"},
        },
        start=0,
    )
    reported_total = page.get("total")
    # Full ID set via pagination (source of truth for match)
    ids: list[int] = []
    start = 0
    while True:
        data = await client.call(
            "crm.deal.list",
            {
                "filter": {"CATEGORY_ID": category_id},
                "select": ["ID"],
                "order": {"ID": "ASC"},
                "start": start,
            },
        )
        batch = data.get("result") or []
        if not isinstance(batch, list):
            break
        for row in batch:
            try:
                ids.append(int(row.get("ID")))
            except (TypeError, ValueError):
                pass
        nxt = data.get("next")
        if nxt is None:
            if len(batch) < 50:
                break
            start += len(batch)
        else:
            start = int(nxt)
        if not batch:
            break
    unique = sorted(set(ids))
    return {
        "category_id": category_id,
        "bitrix_total_field": reported_total,
        "bitrix_ids_fetched": len(ids),
        "bitrix_unique_ids": len(unique),
        "duplicate_ids_in_pages": len(ids) - len(unique),
    }


async def db_stats(session: AsyncSession, cats: list[int]) -> dict[str, Any]:
    async def cnt(model: Any, *where: Any) -> int:
        q = select(func.count()).select_from(model)
        if where:
            q = q.where(*where)
        return int((await session.execute(q)).scalar_one())

    by_cat = {}
    for c in cats:
        by_cat[str(c)] = await cnt(CrmDeal, CrmDeal.category_id == c)

    active = await cnt(CrmDeal, CrmDeal.closed.is_(False), CrmDeal.missing_from_bitrix.is_(False))
    won = await cnt(
        CrmDeal,
        CrmDeal.closed.is_(True),
        CrmDeal.missing_from_bitrix.is_(False),
        CrmDeal.stage_id.in_(select(CrmStage.id).where(CrmStage.semantics == "success")),
    )
    lost = await cnt(
        CrmDeal,
        CrmDeal.closed.is_(True),
        CrmDeal.missing_from_bitrix.is_(False),
        CrmDeal.stage_id.in_(select(CrmStage.id).where(CrmStage.semantics == "failure")),
    )
    missing = await cnt(CrmDeal, CrmDeal.missing_from_bitrix.is_(True))
    overdue = await cnt(
        CrmActivity,
        CrmActivity.completed.is_(False),
        CrmActivity.deadline.is_not(None),
        CrmActivity.deadline < func.now(),
        CrmActivity.owner_type_id == 2,
    )
    no_future = await cnt(
        CrmDeal,
        CrmDeal.closed.is_(False),
        CrmDeal.has_future_activity.is_(False),
        CrmDeal.missing_from_bitrix.is_(False),
    )
    dup_deals = int(
        (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM ("
                    "SELECT bitrix_id FROM crm_deals GROUP BY bitrix_id HAVING COUNT(*) > 1"
                    ") t"
                )
            )
        ).scalar_one()
    )
    dup_acts = int(
        (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM ("
                    "SELECT bitrix_id FROM crm_activities GROUP BY bitrix_id HAVING COUNT(*) > 1"
                    ") t"
                )
            )
        ).scalar_one()
    )

    return {
        "managers": await cnt(CrmManager),
        "pipelines": await cnt(CrmPipeline),
        "stages": await cnt(CrmStage),
        "deals": await cnt(CrmDeal),
        "deals_by_category": by_cat,
        "activities": await cnt(CrmActivity),
        "snapshots": await cnt(DealSnapshot),
        "change_events": await cnt(DealChangeEvent),
        "active": active,
        "won": won,
        "lost": lost,
        "missing_from_bitrix": missing,
        "overdue_activities": overdue,
        "deals_without_future_activity": no_future,
        "duplicate_deal_bitrix_ids": dup_deals,
        "duplicate_activity_bitrix_ids": dup_acts,
    }


def write_md(report: dict[str, Any]) -> None:
    bx = report.get("bitrix_counts") or {}
    pg = report.get("postgres") or {}
    cmp = report.get("comparison") or {}
    runs = report.get("sync_runs") or []
    checks = report.get("checks") or {}
    gates = report.get("gates") or {}

    lines = [
        "# Bitrix Full Initial Sync Report",
        "",
        f"## Status: **{report.get('status')}**",
        "",
        "Controlled full initial sync for categories **1 (Сваи)** and **39 (Отложенный спрос)**.",
        "Bitrix: read-only. Scheduled worker: **not started**.",
        "",
        "## Environment",
        "",
        f"| Key | Value |",
        f"|-----|-------|",
        f"| Portal | focushouse.bitrix24.ru |",
        f"| Webhook | configured=true (sanitized) |",
        f"| Sanitized base | `{report.get('sanitized_base')}` |",
        f"| Categories | `{report.get('categories')}` |",
        f"| Database | `{report.get('database')}` |",
        f"| Started (UTC) | {report.get('started_at')} |",
        f"| Finished (UTC) | {report.get('finished_at')} |",
        f"| Duration (s) | {report.get('duration_seconds')} |",
        "",
        "## 1–2. Deal counts Bitrix vs PostgreSQL",
        "",
        "| Category | Bitrix unique IDs | Bitrix total field | PostgreSQL | Match |",
        "|----------|------------------:|-------------------:|-----------:|:-----:|",
    ]
    for cat in report.get("categories") or []:
        b = (bx.get(str(cat)) or {})
        p = (pg.get("deals_by_category") or {}).get(str(cat), 0)
        m = (cmp.get("by_category") or {}).get(str(cat), {})
        lines.append(
            f"| {cat} | {b.get('bitrix_unique_ids')} | {b.get('bitrix_total_field')} | {p} | "
            f"{'YES' if m.get('match') else 'NO'} |"
        )
    lines += [
        "",
        f"**BITRIX COUNTS MATCH:** {gates.get('BITRIX_COUNTS_MATCH')}",
        "",
        "## 3. Entity totals (PostgreSQL)",
        "",
        "| Entity | Count |",
        "|--------|------:|",
        f"| managers | {pg.get('managers')} |",
        f"| pipelines | {pg.get('pipelines')} |",
        f"| stages | {pg.get('stages')} |",
        f"| deals | {pg.get('deals')} |",
        f"| activities | {pg.get('activities')} |",
        f"| snapshots | {pg.get('snapshots')} |",
        f"| change_events | {pg.get('change_events')} |",
        "",
        "## 4–5. Discrepancies",
        "",
    ]
    discs = report.get("discrepancies") or []
    if not discs:
        lines.append("None.")
    else:
        for d in discs:
            lines.append(f"- {d}")
    lines += [
        "",
        "## 6. Business signals (PostgreSQL)",
        "",
        "| Signal | Count |",
        "|--------|------:|",
        f"| active | {pg.get('active')} |",
        f"| won | {pg.get('won')} |",
        f"| lost | {pg.get('lost')} |",
        f"| missing_from_bitrix | {pg.get('missing_from_bitrix')} |",
        f"| overdue activities | {pg.get('overdue_activities')} |",
        f"| deals without future activity | {pg.get('deals_without_future_activity')} |",
        "",
        "## 7. Sync runs",
        "",
        "| type | status | items | errors | duration_s | cursor |",
        "|------|--------|------:|-------:|-----------:|--------|",
    ]
    for r in runs:
        lines.append(
            f"| {r.get('sync_type')} | {r.get('status')} | {r.get('items_processed')} | "
            f"{r.get('errors_count')} | {r.get('duration_seconds')} | `{r.get('cursor_info')}` |"
        )
    metrics = report.get("client_metrics") or {}
    lines += [
        "",
        f"- retries: **{metrics.get('retry_count')}**",
        f"- rate_limit_events (HTTP 429): **{metrics.get('rate_limit_events')}**",
        f"- network_retries: **{metrics.get('network_retry_count')}**",
        f"- call_counts: `{json.dumps(metrics.get('call_counts') or {}, ensure_ascii=False)}`",
        "",
        "## 8. Integrity checks",
        "",
        f"| Check | Result |",
        f"|-------|--------|",
        f"| duplicates (deals) | {checks.get('duplicate_deals')} |",
        f"| duplicates (activities) | {checks.get('duplicate_activities')} |",
        f"| webhook in logs | {checks.get('webhook_in_logs')} |",
        f"| write methods called | {checks.get('write_methods')} |",
        f"| methods used | `{checks.get('methods_used')}` |",
        f"| last_deals_sync cursor | `{checks.get('last_deals_sync')}` |",
        f"| last_activities_sync cursor | `{checks.get('last_activities_sync')}` |",
        f"| last_full_reconcile | `{checks.get('last_full_reconcile')}` |",
        f"| full reconcile status | {checks.get('full_reconcile_status')} |",
        "",
        "## 9. Tests",
        "",
        f"- pytest: **{report.get('pytest')}**",
        "",
        "## 10. Gates",
        "",
        f"- FULL INITIAL SYNC: **{gates.get('FULL_INITIAL_SYNC')}**",
        f"- BITRIX COUNTS MATCH: **{gates.get('BITRIX_COUNTS_MATCH')}**",
        f"- DATABASE CONSISTENCY: **{gates.get('DATABASE_CONSISTENCY')}**",
        f"- READY FOR SCHEDULED WORKER TEST: **{gates.get('READY_FOR_SCHEDULED_WORKER_TEST')}**",
        "",
        "Scheduled worker was **not** started.",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


async def main() -> int:
    settings = get_settings()
    get_settings.cache_clear()
    settings = get_settings()
    cats = settings.bitrix_category_ids
    if set(cats) != {1, 39}:
        print(f"WARNING: categories={cats}, expected [1, 39]", flush=True)

    db_url = os.environ.get(
        "FULL_SYNC_DATABASE_URL",
        os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/focus_analytics",
        ),
    )
    # Force host URL if docker hostname leaked from .env
    if "@db:" in db_url:
        db_url = "postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/focus_analytics"

    webhook = settings.BITRIX_WEBHOOK_URL or os.environ.get("BITRIX_WEBHOOK_URL", "")
    if not webhook:
        print("BITRIX_WEBHOOK_URL missing", flush=True)
        return 2

    client = BitrixClient(webhook_url=webhook, timeout=60.0, rate_limit_rps=1.5)
    report: dict[str, Any] = {
        "status": "RUNNING",
        "sanitized_base": client.sanitized_base,
        "categories": cats,
        "database": db_url.split("@")[-1] if "@" in db_url else db_url,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    t0 = time.monotonic()
    print(f"FULL SYNC start cats={cats} db={report['database']}", flush=True)

    engine = create_async_engine(db_url, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as session:
        print("Truncating CRM + sync tables...", flush=True)
        await truncate_crm(session)

    # Independent Bitrix counts BEFORE sync (same filter)
    bitrix_counts: dict[str, Any] = {}
    for c in cats:
        print(f"Counting Bitrix deals CATEGORY_ID={c}...", flush=True)
        bitrix_counts[str(c)] = await bitrix_deal_total(client, c)
        print(f"  -> {bitrix_counts[str(c)]}", flush=True)
    report["bitrix_counts"] = bitrix_counts

    # Run sync phases (shared client for metrics)
    async with Session() as session:
        orch = SyncOrchestrator(session, client=client)
        print("Phase: dictionaries", flush=True)
        await orch.run_dictionaries()
    async with Session() as session:
        orch = SyncOrchestrator(session, client=client)
        print("Phase: deals full_reconcile", flush=True)
        await orch.run_deals(full=True)
    async with Session() as session:
        orch = SyncOrchestrator(session, client=client)
        print("Phase: activities full", flush=True)
        await orch.run_activities(full=True)
    async with Session() as session:
        repo = SyncRepository(session)
        await repo.set_state("last_full_reconcile", {"at": datetime.now(timezone.utc).isoformat()})
        await session.commit()

    duration = round(time.monotonic() - t0, 2)
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["duration_seconds"] = duration

    async with Session() as session:
        pg = await db_stats(session, cats)
        report["postgres"] = pg

        runs_rows = (
            await session.execute(select(SyncRun).order_by(SyncRun.started_at.asc()))
        ).scalars().all()
        sync_runs = []
        for r in runs_rows:
            dur = None
            if r.finished_at and r.started_at:
                dur = round((r.finished_at - r.started_at).total_seconds(), 2)
            sync_runs.append(
                {
                    "sync_type": r.sync_type.value if hasattr(r.sync_type, "value") else str(r.sync_type),
                    "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                    "items_processed": r.items_processed,
                    "errors_count": r.errors_count,
                    "error_message": r.error_message,
                    "cursor_info": r.cursor_info,
                    "duration_seconds": dur,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                }
            )
        report["sync_runs"] = sync_runs

        state_keys = ["last_deals_sync", "last_activities_sync", "last_dictionaries_sync", "last_full_reconcile"]
        states = {}
        for k in state_keys:
            st = (
                await session.execute(select(SyncState).where(SyncState.key == k))
            ).scalar_one_or_none()
            states[k] = st.value if st else None

    comparison: dict[str, Any] = {"by_category": {}, "all_match": True}
    discrepancies: list[str] = []
    for c in cats:
        b = bitrix_counts[str(c)]["bitrix_unique_ids"]
        p = pg["deals_by_category"].get(str(c), 0)
        match = b == p
        comparison["by_category"][str(c)] = {
            "bitrix": b,
            "postgres": p,
            "delta": p - b,
            "match": match,
        }
        if not match:
            comparison["all_match"] = False
            discrepancies.append(
                f"CATEGORY_ID={c}: Bitrix unique={b} vs PostgreSQL={p} (delta={p - b})"
            )
        tf = bitrix_counts[str(c)].get("bitrix_total_field")
        if tf is not None and int(tf) != b:
            discrepancies.append(
                f"CATEGORY_ID={c}: Bitrix total field={tf} != unique fetched IDs={b}"
            )
        if bitrix_counts[str(c)].get("duplicate_ids_in_pages", 0):
            discrepancies.append(
                f"CATEGORY_ID={c}: duplicate IDs across Bitrix pages="
                f"{bitrix_counts[str(c)]['duplicate_ids_in_pages']}"
            )

    report["comparison"] = comparison
    report["discrepancies"] = discrepancies

    methods = sorted(client.call_counts.keys())
    write_methods = [m for m in methods if any(x in m for x in (".add", ".update", ".delete", ".set"))]
    full_run = next((r for r in sync_runs if r["sync_type"] == "full_reconcile"), None)
    all_success = all(r["status"] == "success" for r in sync_runs) and bool(sync_runs)

    # Scan this process log text we control — webhook must not appear in report file
    report_text = json.dumps({k: v for k, v in report.items() if k != "raw"}, ensure_ascii=False)
    webhook_leaked = bool(WEBHOOK_PATTERN.search(report_text)) or (
        bool(webhook) and webhook.rstrip("/") in report_text
    )

    checks = {
        "duplicate_deals": pg["duplicate_deal_bitrix_ids"],
        "duplicate_activities": pg["duplicate_activity_bitrix_ids"],
        "webhook_in_logs": "FAIL" if webhook_leaked else "PASS (not in report artifact)",
        "write_methods": write_methods or "none",
        "methods_used": methods,
        "last_deals_sync": states.get("last_deals_sync"),
        "last_activities_sync": states.get("last_activities_sync"),
        "last_full_reconcile": states.get("last_full_reconcile"),
        "full_reconcile_status": full_run["status"] if full_run else "MISSING",
    }
    report["checks"] = checks
    report["client_metrics"] = {
        "call_counts": client.call_counts,
        "retry_count": client.retry_count,
        "rate_limit_events": client.rate_limit_events,
        "network_retry_count": client.network_retry_count,
    }

    sync_pass = (
        all_success
        and pg["duplicate_deal_bitrix_ids"] == 0
        and pg["duplicate_activity_bitrix_ids"] == 0
        and not write_methods
        and checks["full_reconcile_status"] == "success"
        and states.get("last_deals_sync") is not None
        and states.get("last_activities_sync") is not None
        and states.get("last_full_reconcile") is not None
    )
    counts_match = comparison["all_match"]
    db_ok = (
        sync_pass
        and counts_match
        and not webhook_leaked
    )

    report["gates"] = {
        "FULL_INITIAL_SYNC": "PASS" if sync_pass else "FAIL",
        "BITRIX_COUNTS_MATCH": "YES" if counts_match else "NO",
        "DATABASE_CONSISTENCY": "PASS" if db_ok else "FAIL",
        # Worker test readiness: sync OK + counts match; still requires user confirmation
        "READY_FOR_SCHEDULED_WORKER_TEST": "YES" if (sync_pass and counts_match) else "NO",
    }
    report["status"] = report["gates"]["FULL_INITIAL_SYNC"]
    report["pytest"] = "pending"

    await engine.dispose()

    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_md(report)
    print(json.dumps({"gates": report["gates"], "postgres": pg, "comparison": comparison}, ensure_ascii=False, indent=2), flush=True)
    print(f"Wrote {OUT_JSON} and {OUT_MD}", flush=True)
    return 0 if report["gates"]["FULL_INITIAL_SYNC"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

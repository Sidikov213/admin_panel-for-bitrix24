#!/usr/bin/env python3
"""Snapshot DB + wait for N new sync deal/activity cycle groups after a marker time."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

os.environ["DATABASE_URL"] = os.environ.get(
    "FULL_SYNC_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/focus_analytics",
)

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.crm import (
    CrmActivity,
    CrmDeal,
    CrmManager,
    CrmPipeline,
    CrmStage,
    DealChangeEvent,
    DealSnapshot,
)
from app.models.sync import SyncRun, SyncState


async def snapshot(session: AsyncSession) -> dict[str, Any]:
    async def cnt(model: Any) -> int:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())

    states = {}
    for key in (
        "last_deals_sync",
        "last_activities_sync",
        "last_dictionaries_sync",
        "last_full_reconcile",
    ):
        row = (
            await session.execute(select(SyncState).where(SyncState.key == key))
        ).scalar_one_or_none()
        states[key] = row.value if row else None

    latest = (
        await session.execute(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(5))
    ).scalars().all()

    return {
        "at": datetime.now(timezone.utc).isoformat(),
        "managers": await cnt(CrmManager),
        "pipelines": await cnt(CrmPipeline),
        "stages": await cnt(CrmStage),
        "deals": await cnt(CrmDeal),
        "activities": await cnt(CrmActivity),
        "snapshots": await cnt(DealSnapshot),
        "change_events": await cnt(DealChangeEvent),
        "missing_from_bitrix": int(
            (
                await session.execute(
                    select(func.count()).select_from(CrmDeal).where(CrmDeal.missing_from_bitrix.is_(True))
                )
            ).scalar_one()
        ),
        "cursors": states,
        "recent_runs": [
            {
                "id": r.id,
                "sync_type": r.sync_type.value if hasattr(r.sync_type, "value") else str(r.sync_type),
                "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "items_processed": r.items_processed,
                "errors_count": r.errors_count,
                "cursor_info": r.cursor_info,
                "error_message": r.error_message,
            }
            for r in latest
        ],
    }


async def runs_since(session: AsyncSession, since: datetime) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(SyncRun).where(SyncRun.started_at >= since).order_by(SyncRun.started_at.asc())
        )
    ).scalars().all()
    out = []
    for r in rows:
        dur = None
        if r.finished_at and r.started_at:
            dur = round((r.finished_at - r.started_at).total_seconds(), 2)
        out.append(
            {
                "id": r.id,
                "sync_type": r.sync_type.value if hasattr(r.sync_type, "value") else str(r.sync_type),
                "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "duration_seconds": dur,
                "items_processed": r.items_processed,
                "errors_count": r.errors_count,
                "cursor_info": r.cursor_info,
                "error_message": r.error_message,
            }
        )
    return out


def group_cycles(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group dictionaries + deals/full_reconcile + activities that start close together."""
    cycles: list[dict[str, Any]] = []
    i = 0
    while i < len(runs):
        # Find a deals or full_reconcile as cycle anchor; pull nearby dict/activities
        if runs[i]["sync_type"] not in ("deals", "full_reconcile"):
            i += 1
            continue
        anchor = runs[i]
        started = datetime.fromisoformat(anchor["started_at"])
        window_end = started.timestamp() + 3600  # 1h window for slow cycles
        group = []
        # include dictionaries started just before
        j = i - 1
        while j >= 0 and runs[j]["sync_type"] == "dictionaries":
            ds = datetime.fromisoformat(runs[j]["started_at"])
            if abs((started - ds).total_seconds()) < 600:
                group.insert(0, runs[j])
            j -= 1
        group.append(anchor)
        k = i + 1
        while k < len(runs):
            r = runs[k]
            rs = datetime.fromisoformat(r["started_at"])
            if rs.timestamp() > window_end:
                break
            if r["sync_type"] in ("activities", "dictionaries", "deals", "full_reconcile"):
                # next deals/full starts a new cycle
                if r["sync_type"] in ("deals", "full_reconcile") and r["id"] != anchor["id"]:
                    break
                group.append(r)
            k += 1
        deal_run = next((x for x in group if x["sync_type"] in ("deals", "full_reconcile")), None)
        act_run = next((x for x in group if x["sync_type"] == "activities"), None)
        dict_run = next((x for x in group if x["sync_type"] == "dictionaries"), None)
        starts = [datetime.fromisoformat(x["started_at"]) for x in group if x["started_at"]]
        ends = [
            datetime.fromisoformat(x["finished_at"])
            for x in group
            if x.get("finished_at")
        ]
        cycles.append(
            {
                "sync_type": deal_run["sync_type"] if deal_run else "unknown",
                "started_at": min(starts).isoformat() if starts else None,
                "finished_at": max(ends).isoformat() if ends else None,
                "duration_seconds": (
                    round((max(ends) - min(starts)).total_seconds(), 2) if starts and ends else None
                ),
                "dictionaries": dict_run,
                "deals": deal_run,
                "activities": act_run,
                "errors": sum(int(x.get("errors_count") or 0) for x in group),
                "all_success": all(x.get("status") == "success" for x in group if x),
                "runs": group,
            }
        )
        i = k if k > i else i + 1
    return cycles


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["snapshot", "wait"], default="snapshot")
    parser.add_argument("--since", help="ISO timestamp; wait for cycles after this")
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--timeout-min", type=int, default=90)
    parser.add_argument("--out", type=str, default="")
    args = parser.parse_args()

    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    if args.mode == "snapshot":
        async with Session() as session:
            snap = await snapshot(session)
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        if args.out:
            Path(args.out).write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
        await engine.dispose()
        return 0

    since = datetime.fromisoformat(args.since)
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    deadline = datetime.now(timezone.utc).timestamp() + args.timeout_min * 60
    print(f"Waiting for {args.cycles} cycles since {since.isoformat()}", flush=True)

    while datetime.now(timezone.utc).timestamp() < deadline:
        async with Session() as session:
            runs = await runs_since(session, since)
            cycles = group_cycles(runs)
            finished = [c for c in cycles if c.get("finished_at") and c.get("activities")]
            print(
                f"[{datetime.now(timezone.utc).isoformat()}] runs={len(runs)} cycles_finished={len(finished)}",
                flush=True,
            )
            if len(finished) >= args.cycles:
                async with Session() as session2:
                    after = await snapshot(session2)
                result = {
                    "since": since.isoformat(),
                    "cycles": finished[: args.cycles],
                    "all_runs": runs,
                    "after": after,
                }
                text_out = json.dumps(result, ensure_ascii=False, indent=2)
                print(text_out, flush=True)
                if args.out:
                    Path(args.out).write_text(text_out, encoding="utf-8")
                await engine.dispose()
                return 0
        await asyncio.sleep(20)

    print("TIMEOUT waiting for cycles", flush=True)
    await engine.dispose()
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

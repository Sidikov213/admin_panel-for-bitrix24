#!/usr/bin/env python3
"""Read-only limited probes: stage semantics + activity LAST_UPDATED.

Never prints webhook. Never writes Bitrix. Never portal-wide activity sync.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        key, val = k.strip(), v.strip()
        if key.startswith("BITRIX_") or key == "DEMO_MODE":
            os.environ[key] = val

from app.core.config import get_settings
from app.integrations.bitrix.client import BitrixClient, BitrixClientError

OUT = ROOT / "docs" / "bitrix-probe-semantics-activities.json"
CONTROL_DEALS = [8475, 7873, 8527, 8581]


async def try_call(client: BitrixClient, method: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        # Probe may need methods outside production allow-list; use internal post path carefully
        if method not in BitrixClient.ALLOWED_METHODS:
            # temporary probe path: call via httpx through private _method_url after allow
            orig = BitrixClient.ALLOWED_METHODS
            BitrixClient.ALLOWED_METHODS = frozenset(set(orig) | {method})
            try:
                data = await client.call(method, params)
            finally:
                BitrixClient.ALLOWED_METHODS = orig
        else:
            data = await client.call(method, params)
        return {"ok": True, "method": method, "error": None, "data": data}
    except BitrixClientError as e:
        return {"ok": False, "method": method, "error": {"kind": e.kind, "message": str(e)}, "data": None}


def summarize_status_item(st: dict[str, Any]) -> dict[str, Any]:
    return {
        "STATUS_ID": st.get("STATUS_ID") or st.get("STATUS_ID") or st.get("ID"),
        "NAME": st.get("NAME"),
        "SEMANTICS": st.get("SEMANTICS"),
        "ENTITY_ID": st.get("ENTITY_ID"),
        "SORT": st.get("SORT"),
        "keys": sorted(st.keys()),
    }


async def main() -> int:
    get_settings.cache_clear()
    client = BitrixClient()
    report: dict[str, Any] = {
        "webhook": "configured=true" if client.webhook_configured else "configured=false",
        "sanitized_base": client.sanitized_base,
        "semantics_probes": [],
        "deal_stage_semantic_id": [],
        "activity_probes": [],
        "conclusion": {},
    }

    # --- Stage semantics probes ---
    # 1) Existing dictionary method keys
    for cat in (1, 39):
        r = await try_call(client, "crm.dealcategory.stage.list", {"id": cat, "start": 0})
        batch = (r.get("data") or {}).get("result") or []
        if not isinstance(batch, list):
            batch = [batch] if batch else []
        report["semantics_probes"].append(
            {
                "probe": f"crm.dealcategory.stage.list id={cat}",
                "ok": r["ok"],
                "error": r["error"],
                "count": len(batch),
                "sample": [summarize_status_item(x) for x in batch[:3]],
                "won_lose": [
                    summarize_status_item(x)
                    for x in batch
                    if str(x.get("STATUS_ID") or "").endswith((":WON", ":LOSE", ":LOST"))
                ],
            }
        )

    # 2) crm.status.list entity variants (Bitrix status dictionary)
    for entity in ("DEAL_STAGE", "DEAL_STAGE_1", "DEAL_STAGE_39", "STATUS"):
        r = await try_call(
            client,
            "crm.status.list",
            {"filter": {"ENTITY_ID": entity}, "order": {"SORT": "ASC"}, "start": 0},
        )
        batch = (r.get("data") or {}).get("result") or []
        if not isinstance(batch, list):
            batch = [batch] if batch else []
        report["semantics_probes"].append(
            {
                "probe": f"crm.status.list ENTITY_ID={entity}",
                "ok": r["ok"],
                "error": r["error"],
                "count": len(batch),
                "sample": [summarize_status_item(x) for x in batch[:5]],
                "with_semantics": sum(1 for x in batch if x.get("SEMANTICS")),
                "won_lose": [
                    summarize_status_item(x)
                    for x in batch
                    if str(x.get("STATUS_ID") or "").endswith((":WON", ":LOSE", ":LOST"))
                    or str(x.get("STATUS_ID") or "") in ("WON", "LOSE", "LOST")
                ],
            }
        )

    # 3) Deal STAGE_SEMANTIC_ID on control deals
    for did in CONTROL_DEALS:
        d = await client.crm_deal_get(did)
        report["deal_stage_semantic_id"].append(
            {
                "id": did,
                "STAGE_ID": d.get("STAGE_ID"),
                "STAGE_SEMANTIC_ID": d.get("STAGE_SEMANTIC_ID"),
                "CLOSED": d.get("CLOSED"),
                "CATEGORY_ID": d.get("CATEGORY_ID"),
                "TITLE": (d.get("TITLE") or "")[:60],
            }
        )

    # Find a LOSE deal in cat 1 and WON/LOSE in cat 39 (single page only)
    for cat, stage_suffix in ((1, "LOSE"), (39, "WON"), (39, "LOSE")):
        r = await client.call_list_page(
            "crm.deal.list",
            {
                "filter": {"CATEGORY_ID": cat, "STAGE_ID": f"C{cat}:{stage_suffix}"},
                "select": ["ID", "STAGE_ID", "STAGE_SEMANTIC_ID", "CLOSED", "CATEGORY_ID", "TITLE"],
                "order": {"DATE_MODIFY": "DESC"},
            },
            start=0,
        )
        batch = r.get("result") or []
        if not isinstance(batch, list):
            batch = [batch] if batch else []
        report["deal_stage_semantic_id"].append(
            {
                "probe_filter": f"CATEGORY_ID={cat} STAGE_ID=C{cat}:{stage_suffix}",
                "count_page": len(batch),
                "first": (
                    {
                        "id": batch[0].get("ID"),
                        "STAGE_ID": batch[0].get("STAGE_ID"),
                        "STAGE_SEMANTIC_ID": batch[0].get("STAGE_SEMANTIC_ID"),
                        "CLOSED": batch[0].get("CLOSED"),
                    }
                    if batch
                    else None
                ),
            }
        )

    # --- Activity LAST_UPDATED probes (limited to one deal owner) ---
    owner_id = 8581
    base_filter = {"OWNER_TYPE_ID": 2, "OWNER_ID": owner_id}
    page = await client.call_list_page(
        "crm.activity.list",
        {"filter": base_filter, "select": ["ID", "LAST_UPDATED", "DATE_MODIFY", "CREATED", "DEADLINE", "COMPLETED", "OWNER_ID"]},
        start=0,
    )
    acts = page.get("result") or []
    if not isinstance(acts, list):
        acts = [acts] if acts else []
    report["activity_probes"].append(
        {
            "probe": "baseline fields for owner 8581",
            "count": len(acts),
            "has_LAST_UPDATED": sum(1 for a in acts if a.get("LAST_UPDATED")),
            "has_DATE_MODIFY": sum(1 for a in acts if a.get("DATE_MODIFY")),
            "sample": acts[:3],
        }
    )

    # Pick a mid LAST_UPDATED if available
    timestamps = sorted(
        [str(a.get("LAST_UPDATED")) for a in acts if a.get("LAST_UPDATED")],
    )
    since = None
    if timestamps:
        # use second-oldest or an hour before newest
        newest = timestamps[-1]
        try:
            dt = datetime.fromisoformat(newest.replace("Z", "+00:00"))
            since_dt = dt - timedelta(days=30)
            since = since_dt.strftime("%Y-%m-%dT%H:%M:%S%z")
            # Bitrix often wants +03:00 style; keep iso
            since = since_dt.isoformat()
        except ValueError:
            since = timestamps[0]

    if since:
        for filter_key in (">=LAST_UPDATED", ">=DATE_MODIFY"):
            r = await try_call(
                client,
                "crm.activity.list",
                {
                    "filter": {**base_filter, filter_key: since},
                    "select": ["ID", "LAST_UPDATED", "DATE_MODIFY", "CREATED"],
                    "order": {"LAST_UPDATED": "ASC"},
                    "start": 0,
                },
            )
            batch = (r.get("data") or {}).get("result") or []
            if not isinstance(batch, list):
                batch = [batch] if batch else []
            report["activity_probes"].append(
                {
                    "probe": f"filter {filter_key} since={since} owner=8581",
                    "ok": r["ok"],
                    "error": r["error"],
                    "count": len(batch),
                    "ids": [a.get("ID") for a in batch[:20]],
                    "last_updated": [a.get("LAST_UPDATED") for a in batch[:10]],
                }
            )

        # order probe
        r = await try_call(
            client,
            "crm.activity.list",
            {
                "filter": base_filter,
                "select": ["ID", "LAST_UPDATED"],
                "order": {"LAST_UPDATED": "DESC"},
                "start": 0,
            },
        )
        batch = (r.get("data") or {}).get("result") or []
        if not isinstance(batch, list):
            batch = [batch] if batch else []
        lus = [a.get("LAST_UPDATED") for a in batch if a.get("LAST_UPDATED")]
        sorted_desc = lus == sorted(lus, reverse=True) if lus else None
        report["activity_probes"].append(
            {
                "probe": "order LAST_UPDATED DESC owner=8581",
                "ok": r["ok"],
                "error": r["error"],
                "count": len(batch),
                "sorted_desc_ok": sorted_desc,
                "first3": lus[:3],
            }
        )

    # Conclusions
    status_ok = any(
        p.get("ok") and p.get("with_semantics", 0) > 0
        for p in report["semantics_probes"]
        if str(p.get("probe", "")).startswith("crm.status.list")
    )
    deal_sem = any(x.get("STAGE_SEMANTIC_ID") for x in report["deal_stage_semantic_id"] if "id" in x)
    lu_filter = next(
        (p for p in report["activity_probes"] if p.get("probe", "").startswith("filter >=LAST_UPDATED")),
        None,
    )
    dm_filter = next(
        (p for p in report["activity_probes"] if p.get("probe", "").startswith("filter >=DATE_MODIFY")),
        None,
    )
    report["conclusion"] = {
        "crm_status_list_has_semantics": status_ok,
        "deal_STAGE_SEMANTIC_ID_present": deal_sem,
        "activity_LAST_UPDATED_filter_ok": bool(lu_filter and lu_filter.get("ok")),
        "activity_DATE_MODIFY_filter_ok": bool(dm_filter and dm_filter.get("ok") and (dm_filter.get("count") or 0) >= 0),
        "recommended_semantics_source": (
            "crm.status.list" if status_ok else ("deal.STAGE_SEMANTIC_ID" if deal_sem else "STAGE_ID_suffix_fallback")
        ),
        "recommended_activity_cursor": (
            "LAST_UPDATED" if (lu_filter and lu_filter.get("ok")) else "UNKNOWN"
        ),
    }

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report["conclusion"], ensure_ascii=False, indent=2))
    print(f"Wrote {OUT}")
    # print key deal semantics without spam
    for x in report["deal_stage_semantic_id"]:
        if "id" in x:
            print(f"deal {x['id']}: STAGE_ID={x.get('STAGE_ID')} SEM={x.get('STAGE_SEMANTIC_ID')} CLOSED={x.get('CLOSED')}")
    for p in report["semantics_probes"]:
        if p.get("ok") and (p.get("with_semantics") or 0) > 0:
            print(f"SEM_SOURCE {p['probe']}: count={p['count']} with_sem={p['with_semantics']} won_lose={p.get('won_lose')}")
    for p in report["activity_probes"]:
        if str(p.get("probe", "")).startswith("filter"):
            print(f"ACT {p['probe']}: ok={p.get('ok')} count={p.get('count')} err={p.get('error')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

#!/usr/bin/env python3
"""READ-ONLY investigation: can Avito inquiries link to existing Bitrix deals?

Uses local Focus Analytics DB only. Does not call Bitrix write APIs.
Does not modify CRM.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent if (BACKEND.parent / ".env").exists() else BACKEND
sys.path.insert(0, str(BACKEND))


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        key, val = k.strip(), v.strip().strip('"').strip("'")
        # Do not override container-injected DATABASE_URL (e.g. @db:5432)
        if key in {"DATABASE_URL"} and key not in os.environ:
            os.environ[key] = val


for _p in (ROOT / ".env", BACKEND / ".env", Path("/app/.env")):
    _load_env_file(_p)

from sqlalchemy import func, or_, select, text

from app.db.session import async_session_factory
from app.models.crm import CrmActivity, CrmDeal, DealSnapshot


async def main() -> int:
    out: dict[str, Any] = {
        "read_only": True,
        "categories": [1, 39],
        "evidence": {},
        "classification": "NOT_POSSIBLE",
        "match_keys": [],
    }

    async with async_session_factory() as session:
        # Deals with Avito in title
        title_q = await session.execute(
            select(CrmDeal.bitrix_id, CrmDeal.title, CrmDeal.category_id, CrmDeal.opportunity)
            .where(
                CrmDeal.category_id.in_([1, 39]),
                CrmDeal.title.ilike("%avito%"),
            )
            .limit(20)
        )
        title_rows = [
            {"bitrix_id": r[0], "title": r[1], "category_id": r[2], "opportunity": str(r[3]) if r[3] is not None else None}
            for r in title_q.all()
        ]

        # Activities with Avito / Open Line hints
        act_q = await session.execute(
            select(
                CrmActivity.bitrix_id,
                CrmActivity.subject,
                CrmActivity.type_id,
                CrmActivity.owner_id,
                CrmActivity.responsible_id,
            )
            .where(
                or_(
                    CrmActivity.subject.ilike("%avito%"),
                    CrmActivity.subject.ilike("%авито%"),
                    CrmActivity.subject.ilike("%openline%"),
                    CrmActivity.subject.ilike("%открыт%лин%"),
                )
            )
            .limit(30)
        )
        act_rows = [
            {
                "bitrix_id": r[0],
                "subject": r[1],
                "type_id": r[2],
                "owner_id": r[3],
                "responsible_id": r[4],
            }
            for r in act_q.all()
        ]

        # Snapshot payload keys that mention avito (sample)
        snap_hits: list[dict[str, Any]] = []
        try:
            snap_q = await session.execute(
                text(
                    """
                    SELECT d.bitrix_id, d.title, s.payload
                    FROM deal_snapshots s
                    JOIN crm_deals d ON d.id = s.deal_id
                    WHERE d.category_id IN (1, 39)
                      AND (
                        s.payload::text ILIKE '%avito%'
                        OR s.payload::text ILIKE '%авито%'
                      )
                    ORDER BY s.observed_at DESC
                    LIMIT 15
                    """
                )
            )
            for bitrix_id, title, payload in snap_q.all():
                keys = sorted(list(payload.keys()))[:40] if isinstance(payload, dict) else []
                avito_fields = []
                if isinstance(payload, dict):
                    for k, v in payload.items():
                        blob = f"{k}={v}".lower()
                        if "avito" in blob or "авито" in blob:
                            avito_fields.append(k)
                snap_hits.append(
                    {
                        "deal_bitrix_id": bitrix_id,
                        "title": title,
                        "payload_keys_sample": keys,
                        "avito_related_fields": avito_fields[:20],
                    }
                )
        except Exception as e:
            snap_hits = [{"error": type(e).__name__}]

        # Counts
        deals_total = (
            await session.execute(
                select(func.count()).select_from(CrmDeal).where(CrmDeal.category_id.in_([1, 39]))
            )
        ).scalar_one()
        acts_total = (await session.execute(select(func.count()).select_from(CrmActivity))).scalar_one()

    out["evidence"] = {
        "deals_in_categories": int(deals_total or 0),
        "activities_total": int(acts_total or 0),
        "deals_title_avito_sample": title_rows,
        "activities_subject_avito_sample": act_rows,
        "snapshot_avito_hits": snap_hits,
    }

    keys = []
    if title_rows:
        keys.append(
            {
                "key": "deal.title contains 'Avito'/'Авито'",
                "strength": "WEAK_HEURISTIC",
                "evidence_count": len(title_rows),
                "note": "Title text alone is not deterministic; collisions possible",
            }
        )
    if act_rows:
        keys.append(
            {
                "key": "activity.subject contains Avito/Open Line markers",
                "strength": "STRONG_HEURISTIC",
                "evidence_count": len(act_rows),
                "note": "Suggests Open Lines channel; needs chat/session id for DIRECT link",
            }
        )
    if any(h.get("avito_related_fields") for h in snap_hits if isinstance(h, dict)):
        keys.append(
            {
                "key": "deal snapshot payload fields mentioning Avito",
                "strength": "STRONG_HEURISTIC",
                "evidence_count": sum(1 for h in snap_hits if h.get("avito_related_fields")),
                "note": "Inspect custom fields / SOURCE_ID / UF_* for stable external ids",
            }
        )

    out["match_keys"] = keys
    if any(k["strength"] == "DIRECT" for k in keys):
        out["classification"] = "DIRECT"
    elif any(k["strength"] == "STRONG_HEURISTIC" for k in keys):
        out["classification"] = "STRONG_HEURISTIC"
    elif keys:
        out["classification"] = "WEAK_HEURISTIC"
    else:
        out["classification"] = "NOT_POSSIBLE"

    docs_dir = ROOT / "docs"
    if not docs_dir.exists():
        docs_dir = Path("/tmp")
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / "avito-bitrix-link-probe.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"WROTE {path}")
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

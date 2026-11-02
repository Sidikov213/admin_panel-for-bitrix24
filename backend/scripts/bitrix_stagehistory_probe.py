"""Read-only probe: is crm.stagehistory.list available on this portal, and what does it return?

Fetches one page per configured pipeline and prints counts and field shape only
(no deal titles, no webhook secret). Usage inside the backend container:

    docker compose exec backend python scripts/bitrix_stagehistory_probe.py
"""

import asyncio
import sys
from collections import Counter

sys.path.insert(0, ".")

from app.core.config import get_settings  # noqa: E402
from app.integrations.bitrix.client import BitrixClient, BitrixClientError  # noqa: E402


async def main() -> int:
    settings = get_settings()
    client = BitrixClient()
    if not client.webhook_configured:
        print("BITRIX_WEBHOOK_URL is not configured")
        return 2
    print(f"portal: {client.sanitized_base}")
    ok = True
    for cat in settings.bitrix_category_ids:
        try:
            rows = await client.crm_stagehistory_list(filters={"CATEGORY_ID": cat}, max_pages=1)
        except BitrixClientError as e:
            print(f"category {cat}: FAILED kind={e.kind} {e}")
            ok = False
            continue
        print(f"category {cat}: {len(rows)} rows on the first page")
        if rows:
            print(f"  fields: {sorted(rows[0].keys())}")
            print(f"  TYPE_ID: {dict(Counter(str(r.get('TYPE_ID')) for r in rows))}")
            print(f"  STAGE_SEMANTIC_ID: {dict(Counter(str(r.get('STAGE_SEMANTIC_ID')) for r in rows))}")
            print(f"  first CREATED_TIME: {rows[0].get('CREATED_TIME')}")
    print("RESULT:", "available" if ok else "not available — funnel will use observed stage changes")
    return 0 if ok else 1


sys.exit(asyncio.run(main()))

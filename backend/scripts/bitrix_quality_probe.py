"""Read-only probe for card-quality data: deal field dictionary, UF_* in deals, timeline comments.

Prints field names, counts and which UF fields were matched — no deal titles, no comment
text, no webhook secret. Usage inside the backend container:

    docker compose exec backend python scripts/bitrix_quality_probe.py
"""

import asyncio
import sys

sys.path.insert(0, ".")

from app.analytics.card_quality import FIELD_HINTS, resolve_field_hints  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.integrations.bitrix.client import BitrixClient, BitrixClientError  # noqa: E402


async def main() -> int:
    client = BitrixClient()
    if not client.webhook_configured:
        print("BITRIX_WEBHOOK_URL is not configured")
        return 2
    print(f"portal: {client.sanitized_base}")
    ok = True
    try:
        fields = await client.crm_deal_fields()
        uf = {c: m for c, m in fields.items() if c.startswith("UF_")}
        print(f"crm.deal.fields: {len(fields)} fields, {len(uf)} user fields")
        compact = {c: {"label": str(m.get("listLabel") or m.get("formLabel") or m.get("title") or c)} for c, m in uf.items()}
        hints = resolve_field_hints(compact)
        for hint in FIELD_HINTS:
            code = hints.get(hint)
            print(f"  {hint}: {code} «{compact[code]['label']}»" if code else f"  {hint}: NOT FOUND — set it on the «Качество карточек» page")
    except BitrixClientError as e:
        print(f"crm.deal.fields: FAILED kind={e.kind} {e}")
        ok = False

    cat = get_settings().bitrix_category_ids[0]
    page = await client.call_list_page("crm.deal.list", {"filter": {"CATEGORY_ID": cat, "CLOSED": "N"}, "select": ["ID", "UF_*"]})
    deals = page.get("result") or []
    print(f"crm.deal.list with UF_*: {len(deals)} open deals on the first page; UF keys in first: "
          f"{sum(1 for k in (deals[0] if deals else {}) if k.startswith('UF_'))}")
    try:
        ids = [int(d["ID"]) for d in deals[:5]]
        comments = await client.crm_timeline_comments(ids)
        print(f"crm.timeline.comment.list via batch: {len(comments)}/{len(ids)} deals answered, "
              f"{sum(len(v) for v in comments.values())} comments")
        for v in comments.values():
            if len(v) >= 2:
                newest_first = int(v[0]["ID"]) > int(v[-1]["ID"])
                print(f"  order newest-first: {newest_first}")
                break
    except BitrixClientError as e:
        print(f"timeline comments: FAILED kind={e.kind} {e}")
        ok = False
    print("RESULT:", "ok" if ok else "partially unavailable — the panel skips those checks and says so")
    return 0 if ok else 1


sys.exit(asyncio.run(main()))

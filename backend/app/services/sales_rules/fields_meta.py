"""READ ONLY Bitrix deal field metadata sync for required_fields picker."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.bitrix.client import BitrixClient
from app.models.sales_rules import BitrixDealField

logger = logging.getLogger(__name__)


async def sync_deal_fields(session: AsyncSession, client: BitrixClient | None = None) -> dict[str, Any]:
    client = client or BitrixClient()
    raw = await client.crm_deal_fields()
    # Bitrix returns {FIELD: {type, title, ...}, ...}
    if not isinstance(raw, dict):
        return {"ok": False, "error": "unexpected_fields_payload", "count": 0}

    existing = {
        f.field_name: f
        for f in (await session.execute(select(BitrixDealField))).scalars().all()
    }
    upserted = 0
    for name, meta in raw.items():
        if not isinstance(meta, dict):
            continue
        title = meta.get("formLabel") or meta.get("title") or meta.get("listLabel") or name
        if isinstance(title, dict):
            title = title.get("ru") or title.get("en") or name
        row = existing.get(name)
        is_uf = name.startswith("UF_")
        if row is None:
            row = BitrixDealField(field_name=name)
            session.add(row)
        row.title = str(title)[:512]
        row.type = str(meta.get("type") or "")[:64] or None
        row.is_required_in_bitrix = bool(meta.get("isRequired"))
        row.is_multiple = bool(meta.get("isMultiple"))
        row.is_user_field = is_uf
        row.raw = meta
        upserted += 1
    await session.flush()
    logger.info("bitrix_deal_fields_synced count=%s", upserted)
    return {"ok": True, "count": upserted}


async def list_deal_fields(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(select(BitrixDealField).order_by(BitrixDealField.field_name))
    ).scalars().all()
    return [
        {
            "field_name": r.field_name,
            "title": r.title,
            "type": r.type,
            "is_user_field": r.is_user_field,
            "is_required_in_bitrix": r.is_required_in_bitrix,
        }
        for r in rows
    ]

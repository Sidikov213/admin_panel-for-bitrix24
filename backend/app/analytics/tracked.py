"""Who is shown in the per-manager lists.

The portal holds the whole company and people who left. Their deals stay in every
total (the numbers must match Bitrix); only their own rows are hidden.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm import CrmManager


async def untracked_manager_ids(session: AsyncSession) -> set[int]:
    rows = await session.execute(select(CrmManager.id).where(CrmManager.is_tracked.is_(False)))
    return set(rows.scalars())


def only_tracked(rows: list[dict[str, Any]], hidden: set[int]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("manager_id") not in hidden]

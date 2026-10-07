from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password
from app.core.timezone import utc_now
from app.models.auth import User, UserRole
from app.models.crm import CrmDeal, CrmPipeline, CrmStage


@pytest.mark.asyncio
async def test_deals_pagination(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add(
        User(
            email="u@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.viewer,
            is_active=True,
        )
    )
    pipe = CrmPipeline(bitrix_id=1, name="P", sort=0)
    db_session.add(pipe)
    await db_session.flush()
    stage = CrmStage(bitrix_id="S1", pipeline_id=pipe.id, name="N", sort=0)
    db_session.add(stage)
    await db_session.flush()
    now = utc_now()
    for i in range(3):
        db_session.add(
            CrmDeal(
                bitrix_id=100 + i,
                title=f"Deal {i}",
                closed=False,
                stage_id=stage.id,
                date_modify=now,
            )
        )
    await db_session.commit()

    await client.post("/api/v1/auth/login", json={"email": "u@example.com", "password": "password123"})
    r = await client.get("/api/v1/deals", params={"limit": 2, "offset": 0, "sort_by": "title", "sort_dir": "asc"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2

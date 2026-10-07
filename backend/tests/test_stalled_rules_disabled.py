import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password
from app.models.auth import User, UserRole


@pytest.mark.asyncio
async def test_stalled_rules_disabled(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add(
        User(
            email="stalled@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.viewer,
            is_active=True,
        )
    )
    await db_session.commit()
    await client.post(
        "/api/v1/auth/login",
        json={"email": "stalled@example.com", "password": "password123"},
    )
    r = await client.get("/api/v1/stalled", params={"mode": "rules"})
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["items"] == []
    assert "не утвержд" in (body.get("rules_config") or {}).get("note", "").lower() or "регламент" in (
        body.get("disclaimer") or ""
    ).lower()

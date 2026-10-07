import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password
from app.models.auth import User, UserRole


@pytest.mark.asyncio
async def test_login_and_me(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add(
        User(
            email="admin@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.admin,
            is_active=True,
        )
    )
    await db_session.commit()

    r = await client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "password123"})
    assert r.status_code == 200
    assert r.json()["email"] == "admin@example.com"
    csrf = client.cookies.get("focus_csrf")
    r2 = await client.get("/api/v1/auth/me")
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_viewer_cannot_create_target(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add(
        User(
            email="viewer@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.viewer,
            is_active=True,
        )
    )
    await db_session.commit()
    await client.post("/api/v1/auth/login", json={"email": "viewer@example.com", "password": "password123"})
    csrf = client.cookies.get("focus_csrf")
    r = await client.post(
        "/api/v1/targets",
        json={
            "period_type": "month",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "amount": "1000",
            "currency": "RUB",
        },
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert r.status_code == 403

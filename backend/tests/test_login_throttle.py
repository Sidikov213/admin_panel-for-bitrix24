"""The API sits behind a proxy: the login throttle must count visitors, not the proxy."""

from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password
from app.auth.rate_limit import client_ip
from app.core.config import get_settings
from app.models.auth import LoginAttempt, User, UserRole

LOGIN = "/api/v1/auth/login"


def _request(peer: str, forwarded: str | None = None):
    headers = {"x-forwarded-for": forwarded} if forwarded else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


def test_client_ip_reads_forwarded_header_only_from_our_proxy() -> None:
    # Our container in front: the visitor is the hop it reports
    assert client_ip(_request("172.18.0.5", "203.0.113.7")) == "203.0.113.7"
    # Frontend behind Caddy: two of our hops, then the visitor
    assert client_ip(_request("172.18.0.5", "203.0.113.7, 172.18.0.4")) == "203.0.113.7"
    # A visitor cannot pick their own address: whatever they send stays to the left
    assert client_ip(_request("172.18.0.5", "1.1.1.1, 203.0.113.7")) == "203.0.113.7"
    # Direct connection from outside: the header is not ours to trust
    assert client_ip(_request("198.51.100.9", "1.1.1.1")) == "198.51.100.9"
    assert client_ip(_request("172.18.0.5")) == "172.18.0.5"


async def _user(db: AsyncSession, email: str) -> None:
    db.add(User(email=email, password_hash=hash_password("password123"), role=UserRole.viewer, is_active=True))
    await db.commit()


@pytest.mark.asyncio
async def test_stranger_cannot_lock_the_owner_out(client: AsyncClient, db_session: AsyncSession) -> None:
    await _user(db_session, "owner@ex.com")
    stranger = {"X-Forwarded-For": "203.0.113.50"}
    for _ in range(get_settings().LOGIN_MAX_ATTEMPTS):
        r = await client.post(LOGIN, json={"email": "owner@ex.com", "password": "wrong-guess"}, headers=stranger)
        assert r.status_code == 401
    # The stranger is stopped even with the right password
    assert (await client.post(LOGIN, json={"email": "owner@ex.com", "password": "password123"}, headers=stranger)).status_code == 429
    # The owner, from their own address, still gets in
    owner = {"X-Forwarded-For": "198.51.100.20"}
    assert (await client.post(LOGIN, json={"email": "owner@ex.com", "password": "password123"}, headers=owner)).status_code == 200


@pytest.mark.asyncio
async def test_one_address_trying_many_emails_is_stopped(client: AsyncClient, db_session: AsyncSession) -> None:
    await _user(db_session, "real@ex.com")
    headers = {"X-Forwarded-For": "203.0.113.60"}
    codes = []
    for i in range(40):
        r = await client.post(LOGIN, json={"email": f"user{i}@ex.com", "password": "wrong-guess"}, headers=headers)
        codes.append(r.status_code)
    assert codes[0] == 401 and codes[-1] == 429
    assert (await client.post(LOGIN, json={"email": "real@ex.com", "password": "password123"}, headers=headers)).status_code == 429


@pytest.mark.asyncio
async def test_successful_login_forgets_earlier_typos(client: AsyncClient, db_session: AsyncSession) -> None:
    await _user(db_session, "typo@ex.com")
    headers = {"X-Forwarded-For": "198.51.100.30"}
    for _ in range(3):
        await client.post(LOGIN, json={"email": "typo@ex.com", "password": "oops-typo"}, headers=headers)
    assert (await client.post(LOGIN, json={"email": "typo@ex.com", "password": "password123"}, headers=headers)).status_code == 200
    left = (await db_session.execute(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.email == "typo@ex.com"))).scalar_one()
    assert left == 0

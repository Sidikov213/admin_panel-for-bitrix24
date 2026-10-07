import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ready(client: AsyncClient) -> None:
    r = await client.get("/api/v1/ready")
    assert r.status_code == 200

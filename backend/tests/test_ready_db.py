import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_ready_ok_with_db(client: AsyncClient) -> None:
    r = await client.get("/api/v1/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body.get("database") == "ok"


@pytest.mark.asyncio
async def test_health_independent_of_ready(client: AsyncClient) -> None:
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

import pytest
import httpx
from pytest import MonkeyPatch

from app.integrations.bitrix.client import BitrixClient


@pytest.mark.asyncio
async def test_pagination(monkeypatch: MonkeyPatch) -> None:
    calls: list[dict] = []

    async def fake_post(self, url, json=None, **kwargs):
        start = (json or {}).get("start", 0)
        calls.append({"start": start})
        req = httpx.Request("POST", url)
        if start == 0:
            return httpx.Response(200, json={"result": [{"ID": "1"}], "next": 1}, request=req)
        return httpx.Response(200, json={"result": [{"ID": "2"}]}, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = BitrixClient(webhook_url="https://example.bitrix24.ru/rest/1/xxx/")
    items = await client.call_paginated("crm.deal.list", {})
    assert len(items) == 2
    assert calls[0]["start"] == 0


@pytest.mark.asyncio
async def test_retry_on_429(monkeypatch: MonkeyPatch) -> None:
    attempts = {"n": 0}

    async def fake_post(self, url, json=None, **kwargs):
        attempts["n"] += 1
        req = httpx.Request("POST", url)
        if attempts["n"] < 2:
            return httpx.Response(429, json={}, request=req)
        return httpx.Response(200, json={"result": []}, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = BitrixClient(webhook_url="https://example.bitrix24.ru/rest/1/xxx/", max_retries=3)
    data = await client.call("crm.dealcategory.list", {})
    assert "result" in data
    assert attempts["n"] >= 2

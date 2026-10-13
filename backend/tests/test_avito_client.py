"""Unit tests for Avito READ-ONLY client — sanitized fixtures only."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.integrations.avito.client import AvitoClientError, AvitoReadOnlyClient
from app.integrations.avito.config import AvitoAccountCredentials, load_avito_accounts_from_env
from app.integrations.avito.parse import first_response_times, normalize_direction, parse_avito_timestamp
from app.integrations.avito.sanitize import credentials_configured_label, sanitize_avito_text


def _creds() -> AvitoAccountCredentials:
    return AvitoAccountCredentials(
        slot=1,
        name="test",
        client_id="test_client_id",
        client_secret="test_client_secret_value",
    )


def test_sanitize_redacts_bearer_and_secrets() -> None:
    raw = 'Bearer supersecrettoken123456 Authorization: Bearer abcdefghijkl'
    out = sanitize_avito_text(raw)
    assert "supersecrettoken123456" not in out
    assert "***" in out

    raw2 = '{"access_token":"tokentokentoken","refresh_token":"refreshrefresh","client_secret":"secsecsec"}'
    out2 = sanitize_avito_text(raw2)
    assert "tokentokentoken" not in out2
    assert "refreshrefresh" not in out2
    assert "secsecsec" not in out2


def test_credentials_configured_label() -> None:
    assert credentials_configured_label(client_id="a", client_secret="b") == "configured=true"
    assert credentials_configured_label(client_id="", client_secret="b") == "configured=false"


def test_load_accounts_multi_and_legacy() -> None:
    env = {
        "AVITO_ACCOUNT_1_NAME": "Primary",
        "AVITO_ACCOUNT_1_CLIENT_ID": "id1",
        "AVITO_ACCOUNT_1_CLIENT_SECRET": "sec1",
        "AVITO_ACCOUNT_2_CLIENT_ID": "id2",
        "AVITO_ACCOUNT_2_CLIENT_SECRET": "sec2",
        "AVITO_ACCOUNT_2_ENABLED": "false",
    }
    accs = load_avito_accounts_from_env(env)
    assert len(accs) == 2
    assert accs[0].name == "Primary"
    assert accs[1].enabled is False

    legacy = load_avito_accounts_from_env(
        {"AVITO_CLIENT_ID": "legacy", "AVITO_CLIENT_SECRET": "legacy_sec"}
    )
    assert len(legacy) == 1
    assert legacy[0].slot == 1
    assert legacy[0].client_id == "legacy"


def test_parse_timestamp_unix_and_iso() -> None:
    dt = parse_avito_timestamp(1700000000)
    assert dt is not None
    assert dt.year == 2023
    dt2 = parse_avito_timestamp("2026-10-11T12:00:00Z")
    assert dt2 is not None
    assert dt2.tzinfo is not None


def test_normalize_direction() -> None:
    assert normalize_direction("in") == "in"
    assert normalize_direction("out") == "out"
    assert normalize_direction("INCOMING") == "in"
    assert normalize_direction("weird") is None


def test_first_response_times() -> None:
    msgs = [
        {"created": 100, "direction": "in"},
        {"created": 130, "direction": "out"},
        {"created": 90, "direction": "out"},  # before customer — ignored for T2
    ]
    r = first_response_times(msgs)
    assert r["first_response_seconds"] == 30
    assert r["customer_first_at"] is not None
    assert r["manager_first_reply_at"] is not None


@pytest.mark.asyncio
async def test_write_methods_blocked() -> None:
    client = AvitoReadOnlyClient(_creds())
    with pytest.raises(AvitoClientError) as ei:
        await client.get_json("/messenger/v1/accounts/1/chats/x/messages")
    assert ei.value.kind == "policy"


def test_messages_get_allowlisted() -> None:
    client = AvitoReadOnlyClient(_creds())
    client._assert_read_only_path("GET", "/messenger/v3/accounts/1/chats/abc/messages/")

@pytest.mark.asyncio
async def test_auth_parsing_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AvitoReadOnlyClient(_creds())

    class FakeResp:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self):
            return {
                "access_token": "REALTOKENSHOULDNOTLEAK",
                "expires_in": 86400,
                "token_type": "Bearer",
                "scope": "messenger:read",
                "refresh_token": "REFRESHSHOULDNOTLEAK",
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            # Ensure secret not logged via kwargs inspection in test
            assert "client_secret" in kwargs.get("data", {})
            return FakeResp()

    with patch("app.integrations.avito.client.httpx.AsyncClient", return_value=FakeClient()):
        result = await client.authenticate()

    assert result["authenticated"] is True
    assert result["expires_in"] == 86400
    assert result["has_refresh_token"] is True
    assert "REALTOKEN" not in str(result)
    assert "REFRESH" not in str(result)
    dumped = str(result)
    assert "access_token" not in dumped or "REALTOKEN" not in dumped


@pytest.mark.asyncio
async def test_auth_error_sanitized() -> None:
    client = AvitoReadOnlyClient(_creds())

    class FakeResp:
        status_code = 400
        headers = {"content-type": "application/json"}
        text = "bad client_secret=supersecretvalue1234567890"

        def json(self):
            return {"error": "invalid_client", "error_description": "client_secret=supersecretvalue1234567890"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return FakeResp()

    with patch("app.integrations.avito.client.httpx.AsyncClient", return_value=FakeClient()):
        with pytest.raises(AvitoClientError) as ei:
            await client.authenticate()
    assert "supersecretvalue1234567890" not in str(ei.value)


@pytest.mark.asyncio
async def test_retry_on_429() -> None:
    client = AvitoReadOnlyClient(_creds(), max_retries=3, min_interval_s=0)
    client._access_token = "tok"
    client._token_expires_at = 1e18

    calls = {"n": 0}

    class FakeResp:
        def __init__(self, status: int, body: dict):
            self.status_code = status
            self.headers = {"Retry-After": "0", "content-type": "application/json"}
            self._body = body
            self.text = str(body)

        def json(self):
            return self._body

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] < 2:
                return FakeResp(429, {"error": "rate"})
            return FakeResp(200, {"ok": True})

    with patch("app.integrations.avito.client.httpx.AsyncClient", return_value=FakeClient()):
        body = await client.get_json("/core/v1/accounts/self")
    assert body["ok"] is True
    assert client.rate_limit_events >= 1


@pytest.mark.asyncio
async def test_timeout_classified() -> None:
    client = AvitoReadOnlyClient(_creds(), max_retries=1, min_interval_s=0)

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.TimeoutException("slow")

    with patch("app.integrations.avito.client.httpx.AsyncClient", return_value=FakeClient()):
        with pytest.raises(AvitoClientError) as ei:
            await client.authenticate()
    assert ei.value.kind == "timeout"

"""READ-ONLY Avito Business API client (Phase 1 probe).

Hard rules:
- Never send messages / edit items / change prices.
- Never log client_secret, access_token, refresh_token, Authorization headers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from app.integrations.avito.config import AvitoAccountCredentials
from app.integrations.avito.sanitize import credentials_configured_label, sanitize_avito_text

logger = logging.getLogger(__name__)

TOKEN_URL = "https://api.avito.ru/token"
API_BASE = "https://api.avito.ru"

# Explicit allow-list of relative paths (method + path template family).
ALLOWED_GET_PREFIXES = (
    "/core/v1/accounts/self",
    "/core/v1/items",
    "/messenger/v2/accounts/",
    "/messenger/v3/accounts/",
)

FORBIDDEN_WRITE_MARKERS = (
    "/messages",  # POST send — blocked unless GET .../messages/
    "/blacklist",
    "/webhook",
    "/uploadImages",
    "/read",
)


class AvitoClientError(Exception):
    def __init__(
        self,
        message: str,
        *,
        kind: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(sanitize_avito_text(message))
        self.kind = kind
        self.status_code = status_code


class AvitoReadOnlyClient:
    """Minimal OAuth client_credentials client with GET-only API calls."""

    def __init__(
        self,
        credentials: AvitoAccountCredentials,
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
        min_interval_s: float = 0.35,
    ) -> None:
        self._creds = credentials
        self._timeout = timeout
        self._max_retries = max_retries
        self._min_interval = min_interval_s
        self._lock = asyncio.Lock()
        self._last_call = 0.0
        self._access_token: str | None = None
        self._token_expires_at: float | None = None
        self._token_expires_in: int | None = None
        self.call_counts: dict[str, int] = {}
        self.retry_count = 0
        self.rate_limit_events = 0
        self.last_retry_after: str | None = None

    @property
    def configured(self) -> bool:
        return self._creds.configured

    @property
    def configured_label(self) -> str:
        return credentials_configured_label(
            client_id=self._creds.client_id,
            client_secret=self._creds.client_secret,
        )

    @property
    def account_name(self) -> str:
        return self._creds.name

    @property
    def token_expires_in(self) -> int | None:
        return self._token_expires_in

    async def _throttle(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_call = time.monotonic()

    def _assert_read_only_path(self, method: str, path: str) -> None:
        if method.upper() != "GET":
            raise AvitoClientError(f"write_method_blocked:{method}", kind="policy")
        # Allow GET messages list (ends with /messages/ or contains /messages/? )
        lower = path.lower()
        if any(m in lower for m in ("/blacklist", "/webhook", "/uploadimages")):
            raise AvitoClientError(f"path_blocked:{path}", kind="policy")
        # Block chat "read" mark-as-read side effect
        if "/read" in lower and "/messages" not in lower:
            raise AvitoClientError(f"path_blocked:{path}", kind="policy")
        if not any(path.startswith(p) for p in ALLOWED_GET_PREFIXES):
            raise AvitoClientError(f"path_not_allowlisted:{path}", kind="policy")

    async def authenticate(self) -> dict[str, Any]:
        if not self.configured:
            raise AvitoClientError("credentials_not_configured", kind="config")

        await self._throttle()
        data = {
            "grant_type": "client_credentials",
            "client_id": self._creds.client_id,
            "client_secret": self._creds.client_secret,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    TOKEN_URL,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
        except httpx.TimeoutException as e:
            raise AvitoClientError("auth_timeout", kind="timeout") from e
        except httpx.HTTPError as e:
            raise AvitoClientError(f"auth_network:{type(e).__name__}", kind="network") from e

        body: dict[str, Any] = {}
        try:
            if resp.headers.get("content-type", "").startswith("application/json"):
                body = resp.json()
        except Exception:
            body = {}

        if resp.status_code >= 400:
            err = body.get("error") or body.get("error_description") or resp.text[:200]
            raise AvitoClientError(
                f"auth_failed status={resp.status_code} err={sanitize_avito_text(str(err))}",
                kind="auth",
                status_code=resp.status_code,
            )

        token = body.get("access_token")
        if not token:
            raise AvitoClientError("auth_missing_access_token", kind="auth")

        expires_in = int(body.get("expires_in") or 0)
        self._access_token = str(token)
        self._token_expires_in = expires_in or None
        self._token_expires_at = time.monotonic() + max(expires_in - 60, 60) if expires_in else None

        # Never return raw tokens
        return {
            "authenticated": True,
            "token_type": body.get("token_type") or "Bearer",
            "expires_in": expires_in or None,
            "scope": body.get("scope"),
            "has_refresh_token": bool(body.get("refresh_token")),
        }

    async def _ensure_token(self) -> None:
        if self._access_token and (
            self._token_expires_at is None or time.monotonic() < self._token_expires_at
        ):
            return
        await self.authenticate()

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._assert_read_only_path("GET", path)
        await self._ensure_token()
        assert self._access_token

        qs = f"?{urlencode(params)}" if params else ""
        url = f"{API_BASE}{path}{qs}"
        key = path.split("?")[0]
        self.call_counts[key] = self.call_counts.get(key, 0) + 1

        last_err: Exception | None = None
        for attempt in range(self._max_retries):
            await self._throttle()
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(
                        url,
                        headers={"Authorization": f"Bearer {self._access_token}"},
                    )
            except httpx.TimeoutException as e:
                last_err = AvitoClientError("request_timeout", kind="timeout")
                self.retry_count += 1
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            except httpx.HTTPError as e:
                last_err = AvitoClientError(f"network:{type(e).__name__}", kind="network")
                self.retry_count += 1
                await asyncio.sleep(0.5 * (attempt + 1))
                continue

            if resp.status_code == 401 and attempt == 0:
                self._access_token = None
                await self._ensure_token()
                self.retry_count += 1
                continue

            if resp.status_code == 429:
                self.rate_limit_events += 1
                self.last_retry_after = resp.headers.get("Retry-After")
                self.retry_count += 1
                delay = float(self.last_retry_after or (1.0 + attempt))
                await asyncio.sleep(min(delay, 10.0))
                continue

            body: Any = {}
            try:
                body = resp.json()
            except Exception:
                body = {"raw_text": sanitize_avito_text(resp.text[:300])}

            if resp.status_code >= 400:
                raise AvitoClientError(
                    f"http_{resp.status_code}:{sanitize_avito_text(str(body)[:300])}",
                    kind="http",
                    status_code=resp.status_code,
                )

            if isinstance(body, dict):
                return body
            return {"data": body}

        raise last_err or AvitoClientError("request_failed", kind="unknown")

    # ---- Convenience READ helpers ----

    async def get_self(self) -> dict[str, Any]:
        return await self.get_json("/core/v1/accounts/self")

    async def list_items(self, *, per_page: int = 10, page: int = 1) -> dict[str, Any]:
        return await self.get_json(
            "/core/v1/items",
            params={"per_page": per_page, "page": page},
        )

    async def list_chats(self, user_id: int | str, *, limit: int = 10, offset: int = 0) -> dict[str, Any]:
        return await self.get_json(
            f"/messenger/v2/accounts/{user_id}/chats",
            params={"limit": limit, "offset": offset, "unread_only": "false"},
        )

    async def get_chat(self, user_id: int | str, chat_id: str) -> dict[str, Any]:
        return await self.get_json(f"/messenger/v2/accounts/{user_id}/chats/{chat_id}")

    async def list_messages(
        self,
        user_id: int | str,
        chat_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        return await self.get_json(
            f"/messenger/v3/accounts/{user_id}/chats/{chat_id}/messages/",
            params={"limit": limit, "offset": offset},
        )

"""Read-only Avito API client (OAuth client credentials + Messenger API).

Only GET requests to an allow-list of paths are possible; sending messages, marking chats
read or anything else that changes the account is rejected before a request is made.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.avito.ru"
TOKEN_PATH = "/token"
# GET-only endpoints the panel may call
ALLOWED_GET = (
    re.compile(r"^/core/v1/accounts/self$"),
    re.compile(r"^/messenger/v2/accounts/\d+/chats$"),
    re.compile(r"^/messenger/v3/accounts/\d+/chats/[^/]+/messages/?$"),
)


class AvitoError(Exception):
    def __init__(self, message: str, *, kind: str = "avito_error", status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status


class _RateLimiter:
    def __init__(self, rps: float) -> None:
        self._interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        if not self._interval:
            return
        async with self._lock:
            delta = time.monotonic() - self._last
            if delta < self._interval:
                await asyncio.sleep(self._interval - delta)
            self._last = time.monotonic()


class AvitoClient:
    def __init__(
        self,
        account: dict[str, Any],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        rate_limit_rps: float | None = None,
        timeout: float = 20.0,
        max_retries: int = 3,
    ) -> None:
        self.account_id = int(account["id"])
        self._client_id = account["client_id"]
        self._client_secret = account["client_secret"]
        self._transport = transport
        self._timeout = timeout
        self._max_retries = max_retries
        self._limiter = _RateLimiter(rate_limit_rps if rate_limit_rps is not None else get_settings().AVITO_RATE_LIMIT_RPS)
        self._token: str | None = None
        self._token_expires = 0.0

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=BASE_URL, timeout=self._timeout, transport=self._transport, trust_env=False)

    async def _get_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires - 60:
            return self._token
        async with self._http() as http:
            try:
                resp = await http.post(
                    TOKEN_PATH,
                    data={"grant_type": "client_credentials", "client_id": self._client_id, "client_secret": self._client_secret},
                )
            except httpx.HTTPError as e:
                raise AvitoError(f"token request failed: {type(e).__name__}", kind="network") from None
        if resp.status_code != 200:
            # Never echo the response: it may contain the client id
            raise AvitoError(f"token request rejected: HTTP {resp.status_code}", kind="invalid_credentials", status=resp.status_code)
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise AvitoError("token response has no access_token", kind="invalid_credentials")
        self._token = str(token)
        self._token_expires = time.monotonic() + float(data.get("expires_in") or 3600)
        return self._token

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not any(p.match(path) for p in ALLOWED_GET):
            raise AvitoError(f"Path not allowed by read-only client: {path}", kind="forbidden_path")
        for attempt in range(self._max_retries):
            await self._limiter.wait()
            token = await self._get_token()
            async with self._http() as http:
                try:
                    resp = await http.get(path, params=params, headers={"Authorization": f"Bearer {token}"})
                except httpx.HTTPError as e:
                    if attempt + 1 == self._max_retries:
                        raise AvitoError(f"request failed: {type(e).__name__}", kind="network") from None
                    await asyncio.sleep(2**attempt)
                    continue
            if resp.status_code == 401 and attempt + 1 < self._max_retries:
                self._token = None  # expired early: get a new one
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt + 1 < self._max_retries:
                await asyncio.sleep(2**attempt)
                continue
            if resp.status_code == 403:
                raise AvitoError(
                    "HTTP 403: no access to this API (tariff or permissions of the account)", kind="forbidden", status=403
                )
            if resp.status_code >= 400:
                raise AvitoError(f"HTTP {resp.status_code} on {path}", kind="http_error", status=resp.status_code)
            return resp.json()
        raise AvitoError(f"giving up on {path}", kind="http_error")

    async def self_info(self) -> dict[str, Any]:
        data = await self.get("/core/v1/accounts/self")
        return data if isinstance(data, dict) else {}

    async def list_chats(self, *, offset: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        data = await self.get(
            f"/messenger/v2/accounts/{self.account_id}/chats",
            {"limit": limit, "offset": offset, "chat_types": "u2i,u2u"},
        )
        chats = data.get("chats") if isinstance(data, dict) else data
        return chats if isinstance(chats, list) else []

    async def list_messages(self, chat_id: str, *, offset: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        data = await self.get(
            f"/messenger/v3/accounts/{self.account_id}/chats/{chat_id}/messages/", {"limit": limit, "offset": offset}
        )
        msgs = data.get("messages") if isinstance(data, dict) else data
        return msgs if isinstance(msgs, list) else []

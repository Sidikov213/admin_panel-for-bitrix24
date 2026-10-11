import asyncio
import logging
import time
from typing import Any
from urllib.parse import urljoin

import httpx

from app.core.config import get_settings
from app.integrations.bitrix.sanitize import sanitize_bitrix_text, sanitize_bitrix_url

logger = logging.getLogger(__name__)


class BitrixClientError(Exception):
    def __init__(self, message: str, *, kind: str | None = None) -> None:
        super().__init__(sanitize_bitrix_text(message))
        self.kind = kind


class BitrixRateLimiter:
    def __init__(self, rps: float) -> None:
        self._min_interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def wait(self) -> None:
        if self._min_interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_call = time.monotonic()


class BitrixClient:
    """Read-only Bitrix24 REST client via inbound webhook.

    Limitations (Stage 1):
    - Webhook exposes only permitted methods; missing CRM fields arrive as null.
    - Date fields may lack timezone; see parse_bitrix_datetime in app.core.timezone.
    - STAGE_ID is a string status code; pipeline/category mapping depends on prior dictionary sync.
    """

    # Methods this client is allowed to invoke (static allow-list).
    ALLOWED_METHODS = frozenset(
        {
            "crm.deal.list",
            "crm.deal.get",
            "crm.activity.list",
            "user.get",
            "user.search",
            "crm.dealcategory.list",
            "crm.dealcategory.stage.list",
            # Live Stage 1.5: dealcategory.stage.list returns SEMANTICS=null;
            # crm.status.list provides S/F/P for DEAL_STAGE_{category}.
            "crm.status.list",
            # Stage 2.5: field metadata for required_fields picker (READ ONLY)
            "crm.deal.fields",
            # Manager Control V1: workday status only (READ ONLY — no open/close/pause/settings.set)
            "timeman.status",
        }
    )

    def __init__(
        self,
        webhook_url: str | None = None,
        rate_limit_rps: float | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        settings = get_settings()
        self._base = (webhook_url or settings.BITRIX_WEBHOOK_URL).rstrip("/") + "/"
        if not self._base or self._base == "/":
            self._base = ""
        self._limiter = BitrixRateLimiter(rate_limit_rps or settings.BITRIX_RATE_LIMIT_RPS)
        self._timeout = timeout or settings.BITRIX_REQUEST_TIMEOUT
        self._max_retries = max_retries or settings.BITRIX_RETRY_MAX
        self.call_counts: dict[str, int] = {}
        self.retry_count: int = 0
        self.rate_limit_events: int = 0
        self.network_retry_count: int = 0

    @property
    def webhook_configured(self) -> bool:
        return bool(self._base)

    @property
    def sanitized_base(self) -> str:
        return sanitize_bitrix_url(self._base) if self._base else ""

    def _method_url(self, method: str) -> str:
        return urljoin(self._base, f"{method}.json")

    def _classify_error(self, message: str, status: int | None = None) -> str:
        low = message.lower()
        if status == 429 or "too many" in low or "query limit" in low:
            return "rate_limit"
        if status is not None and status >= 500:
            return "bitrix_5xx"
        if "insufficient_scope" in low or "access_denied" in low and "scope" in low:
            return "insufficient_scope"
        if "access_denied" in low or "forbidden" in low or "permission" in low:
            return "forbidden_crm"
        if "invalid_credentials" in low or "wrong_auth" in low or "unauthorized" in low:
            return "invalid_webhook"
        if "expired" in low:
            return "expired_webhook"
        if "timeout" in low or "timed out" in low:
            return "timeout"
        return "bitrix_error"

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._base:
            raise BitrixClientError("BITRIX_WEBHOOK_URL is not configured", kind="not_configured")
        if method not in self.ALLOWED_METHODS:
            raise BitrixClientError(f"Method not allowed by read-only client: {method}", kind="forbidden_method")
        url = self._method_url(method)
        payload = params or {}
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            await self._limiter.wait()
            try:
                # trust_env=False avoids Windows proxy hijacking local/webhook calls
                async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
                    resp = await client.post(url, json=payload)
                self.call_counts[method] = self.call_counts.get(method, 0) + 1
                if resp.status_code == 429 or resp.status_code >= 500:
                    self.retry_count += 1
                    if resp.status_code == 429:
                        self.rate_limit_events += 1
                    backoff = min(2**attempt, 30)
                    logger.warning(
                        "bitrix_retry method=%s status=%s attempt=%s base=%s",
                        method,
                        resp.status_code,
                        attempt,
                        self.sanitized_base,
                    )
                    await asyncio.sleep(backoff)
                    continue
                if resp.status_code >= 400:
                    kind = self._classify_error(resp.text or "", status=resp.status_code)
                    raise BitrixClientError(
                        f"HTTP {resp.status_code} calling {method}",
                        kind=kind,
                    )
                data = resp.json()
                if "error" in data:
                    desc = str(data.get("error_description") or data["error"])
                    kind = self._classify_error(desc, status=resp.status_code)
                    raise BitrixClientError(desc, kind=kind)
                return data
            except BitrixClientError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exc = e
                self.retry_count += 1
                self.network_retry_count += 1
                logger.warning(
                    "bitrix_network_retry method=%s attempt=%s base=%s err=%s",
                    method,
                    attempt,
                    self.sanitized_base,
                    type(e).__name__,
                )
                await asyncio.sleep(min(2**attempt, 30))
        if last_exc:
            raise BitrixClientError(
                f"{type(last_exc).__name__} calling {method}",
                kind="timeout" if isinstance(last_exc, httpx.TimeoutException) else "network",
            ) from None
        raise BitrixClientError(f"Bitrix call failed after retries: {method}", kind="bitrix_error")

    async def call_paginated(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        result_key: str = "result",
    ) -> list[Any]:
        """Bitrix list pagination via `start` offset."""
        items: list[Any] = []
        start = 0
        base = dict(params or {})
        while True:
            page_params = {**base, "start": start}
            data = await self.call(method, page_params)
            batch = data.get(result_key)
            if batch is None:
                break
            if not isinstance(batch, list):
                items.append(batch)
                break
            items.extend(batch)
            next_start = data.get("next")
            if next_start is None:
                if len(batch) < 50:
                    break
                start += len(batch)
            else:
                start = int(next_start)
            if not batch:
                break
        return items

    async def call_list_page(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        start: int = 0,
    ) -> dict[str, Any]:
        """Fetch a single list page (no pagination walk) — for controlled smoke."""
        page_params = {**(params or {}), "start": start}
        return await self.call(method, page_params)

    async def crm_deal_list(self, **filters: Any) -> list[dict[str, Any]]:
        return await self.call_paginated("crm.deal.list", {"filter": filters, "select": ["*"]})

    async def crm_deal_get(self, deal_id: int) -> dict[str, Any]:
        data = await self.call("crm.deal.get", {"id": deal_id})
        return data.get("result") or {}

    async def crm_activity_list(self, **filters: Any) -> list[dict[str, Any]]:
        return await self.call_paginated("crm.activity.list", {"filter": filters, "select": ["*"]})

    async def user_get(self, user_id: int) -> dict[str, Any]:
        data = await self.call("user.get", {"ID": user_id})
        result = data.get("result")
        if isinstance(result, list) and result:
            return result[0]
        return result if isinstance(result, dict) else {}

    async def user_search(self) -> list[dict[str, Any]]:
        return await self.call_paginated("user.search", {})

    async def crm_dealcategory_list(self) -> list[dict[str, Any]]:
        return await self.call_paginated("crm.dealcategory.list", {})

    async def crm_dealcategory_stage_list(self, category_id: int) -> list[dict[str, Any]]:
        return await self.call_paginated(
            "crm.dealcategory.stage.list",
            {"id": category_id},
        )

    async def crm_status_list(self, *, entity_id: str) -> list[dict[str, Any]]:
        """Deal/stage status dictionary (includes SEMANTICS)."""
        return await self.call_paginated(
            "crm.status.list",
            {"filter": {"ENTITY_ID": entity_id}, "order": {"SORT": "ASC"}},
        )

    async def crm_deal_fields(self) -> dict[str, Any]:
        """READ ONLY deal field metadata (standard + UF_*)."""
        data = await self.call("crm.deal.fields", {})
        result = data.get("result", data)
        return result if isinstance(result, dict) else {}

    async def timeman_status(self, user_id: int | None = None) -> dict[str, Any]:
        """READ ONLY current workday status. Never open/close/pause."""
        params: dict[str, Any] = {}
        if user_id is not None:
            params["USER_ID"] = user_id
        data = await self.call("timeman.status", params)
        result = data.get("result", data)
        return result if isinstance(result, dict) else {}

    async def ping(self) -> bool:
        try:
            await self.call("crm.dealcategory.list", {"start": 0})
            return True
        except Exception:
            return False

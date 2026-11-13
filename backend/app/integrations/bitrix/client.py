import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlencode, urljoin

import httpx

from app.core.config import get_settings
from app.integrations.bitrix.sanitize import sanitize_bitrix_text, sanitize_bitrix_url

logger = logging.getLogger(__name__)


def _bitrix_query(params: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """Nested params → Bitrix query pairs: {"filter": {"ID": 1}} → [("filter[ID]", "1")]."""
    pairs: list[tuple[str, str]] = []
    for key, value in params.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, dict):
            pairs += _bitrix_query(value, name)
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    pairs += _bitrix_query(item, f"{name}[{i}]")
                else:
                    pairs.append((f"{name}[{i}]", str(item)))
        elif value is not None:
            pairs.append((name, str(value)))
    return pairs


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
            # Stage transition history with Bitrix timestamps (read-only)
            "crm.stagehistory.list",
            # Card quality: field dictionary (labels of UF_* fields) and timeline comments
            "crm.deal.fields",
            "crm.timeline.comment.list",
        }
    )
    # `batch` only bundles calls; every inner command must itself be in ALLOWED_METHODS
    BATCH_METHOD = "batch"
    BATCH_LIMIT = 50
    PAGE_SIZE = 50
    # Safety net for list pagination: 5000 pages = 250 000 rows, far above this portal
    MAX_PAGES = 5000

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
        # One connection pool for the client's lifetime: a TLS handshake per request is slow
        # and is exactly what fails on a flaky network
        self._http: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            # trust_env=False avoids Windows proxy hijacking local/webhook calls
            self._http = httpx.AsyncClient(timeout=self._timeout, trust_env=False)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
        self._http = None

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
        if method not in self.ALLOWED_METHODS:
            raise BitrixClientError(f"Method not allowed by read-only client: {method}", kind="forbidden_method")
        return await self._call_unchecked(method, params)

    async def _call_unchecked(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Transport only. Callers enforce the allow-list (call_batch checks every inner command)."""
        if not self._base:
            raise BitrixClientError("BITRIX_WEBHOOK_URL is not configured", kind="not_configured")
        url = self._method_url(method)
        payload = params or {}
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            await self._limiter.wait()
            try:
                resp = await self._client().post(url, json=payload)
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
                # The pooled connection may be the broken one: start the retry on a fresh pool
                await self.aclose()
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
        """Bitrix list pagination via `start` offset.

        Bitrix sends `next` while more rows exist. Asking for a `start` past the end does not
        return an empty page: it returns the last page again, so the loop must stop on its own
        evidence (`next`, `total`, a short page, a repeated page) and never on an empty answer.
        """
        items: list[Any] = []
        start = 0
        base = dict(params or {})
        prev_page_key: Any = None
        for _ in range(self.MAX_PAGES):
            data = await self.call(method, {**base, "start": start})
            batch = data.get(result_key)
            if batch is None:
                break
            if not isinstance(batch, list):
                items.append(batch)
                break
            if not batch:
                break
            page_key = self._page_key(batch)
            if page_key is not None and page_key == prev_page_key:
                # Same page served twice: we are past the end
                break
            prev_page_key = page_key
            items.extend(batch)
            next_start = data.get("next")
            if next_start is not None:
                start = int(next_start)
                continue
            total = data.get("total")
            if isinstance(total, int) and len(items) >= total:
                break
            if len(batch) < self.PAGE_SIZE:
                break
            start += len(batch)
        else:
            raise BitrixClientError(f"pagination did not finish in {self.MAX_PAGES} pages: {method}", kind="bitrix_error")
        return items

    @staticmethod
    def _page_key(batch: list[Any]) -> Any:
        """Identity of a page: ids of its first and last rows (None when rows have no id)."""
        first, last = batch[0], batch[-1]
        if isinstance(first, dict) and isinstance(last, dict):
            a, b = first.get("ID", first.get("id")), last.get("ID", last.get("id"))
            if a is not None and b is not None:
                return (a, b, len(batch))
        return None

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
        # "*" does not include user fields; card-quality checks need UF_* (прибыль, дата монтажа…)
        return await self.call_paginated("crm.deal.list", {"filter": filters, "select": ["*", "UF_*"]})

    async def call_batch(self, commands: dict[str, tuple[str, dict[str, Any]]]) -> dict[str, Any]:
        """Up to 50 read-only calls in one request. Returns {key: result}; failed keys are absent."""
        if len(commands) > self.BATCH_LIMIT:
            raise BitrixClientError(f"batch accepts at most {self.BATCH_LIMIT} commands", kind="bitrix_error")
        cmd: dict[str, str] = {}
        for key, (method, params) in commands.items():
            if method not in self.ALLOWED_METHODS:
                raise BitrixClientError(f"Method not allowed by read-only client: {method}", kind="forbidden_method")
            cmd[key] = f"{method}?{urlencode(_bitrix_query(params))}"
        data = await self._call_unchecked(self.BATCH_METHOD, {"halt": 0, "cmd": cmd})
        result = data.get("result") or {}
        errors = result.get("result_error") or {}
        if errors:
            logger.warning("bitrix_batch_partial_errors count=%s", len(errors))
        out = result.get("result") or {}
        return out if isinstance(out, dict) else {}

    async def crm_timeline_comments(self, deal_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        """Latest timeline comments (first page, newest first) for each deal, batched."""
        out: dict[int, list[dict[str, Any]]] = {}
        for i in range(0, len(deal_ids), self.BATCH_LIMIT):
            chunk = deal_ids[i : i + self.BATCH_LIMIT]
            res = await self.call_batch(
                {
                    f"d{d}": (
                        "crm.timeline.comment.list",
                        {
                            "filter": {"ENTITY_ID": d, "ENTITY_TYPE": "deal"},
                            "select": ["ID", "CREATED", "ENTITY_ID", "AUTHOR_ID", "COMMENT"],
                            "order": {"ID": "DESC"},
                        },
                    )
                    for d in chunk
                }
            )
            for d in chunk:
                rows = res.get(f"d{d}")
                if isinstance(rows, list):
                    out[d] = rows
        return out

    async def crm_deal_fields(self) -> dict[str, Any]:
        data = await self.call("crm.deal.fields", {})
        result = data.get("result")
        return result if isinstance(result, dict) else {}

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

    async def crm_stagehistory_list(self, *, filters: dict[str, Any], max_pages: int | None = None) -> list[dict[str, Any]]:
        """Deal stage history (entityTypeId=2), oldest first.

        Unlike other list methods the page lives in result.items, not result.
        """
        items: list[dict[str, Any]] = []
        start = 0
        pages = 0
        while True:
            data = await self.call(
                "crm.stagehistory.list",
                {"entityTypeId": 2, "filter": filters, "order": {"ID": "ASC"}, "start": start},
            )
            result = data.get("result")
            batch = result.get("items") if isinstance(result, dict) else result
            if not isinstance(batch, list) or not batch:
                break
            items.extend(batch)
            pages += 1
            next_start = data.get("next")
            if next_start is None or (max_pages is not None and pages >= max_pages):
                break
            start = int(next_start)
        return items

    async def ping(self) -> bool:
        try:
            await self.call("crm.dealcategory.list", {"start": 0})
            return True
        except Exception:
            return False

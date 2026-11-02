"""Minimal Telegram Bot API client (sendMessage only)."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

# Telegram limit is 4096 characters per message; keep headroom
MAX_MESSAGE_LEN = 4000


class TelegramError(Exception):
    """Raised without the request URL: the bot token is part of it."""


def split_message(text: str, limit: int = MAX_MESSAGE_LEN) -> list[str]:
    """Split on line boundaries so HTML tags (always within one line) stay balanced."""
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


class TelegramClient:
    BASE_URL = "https://api.telegram.org"

    def __init__(
        self,
        token: str,
        *,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token.strip()
        self._timeout = timeout
        self._transport = transport

    async def send_message(self, chat_id: str, text: str) -> None:
        url = f"{self.BASE_URL}/bot{self._token}/sendMessage"
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport, trust_env=False) as client:
            for chunk in split_message(text):
                try:
                    resp = await client.post(
                        url,
                        json={
                            "chat_id": chat_id,
                            "text": chunk,
                            "parse_mode": "HTML",
                            "disable_web_page_preview": True,
                        },
                    )
                except httpx.HTTPError as e:
                    raise TelegramError(f"Telegram request failed: {type(e).__name__}") from None
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                if resp.status_code != 200 or not data.get("ok"):
                    desc = str(data.get("description") or f"HTTP {resp.status_code}")
                    raise TelegramError(f"Telegram rejected message: {desc}".replace(self._token, "***"))

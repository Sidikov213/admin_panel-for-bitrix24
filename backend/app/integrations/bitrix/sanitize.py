"""Redact Bitrix webhook secrets from URLs and log/error text."""

from __future__ import annotations

import re

_REST_TOKEN_RE = re.compile(r"(/rest/)[^/\s\"']+/[^/\s\"']+", re.IGNORECASE)
_TOKEN_FRAGMENT_RE = re.compile(r"(bitrix24\.[a-z.]+/rest/)[^\s\"']+", re.IGNORECASE)


def sanitize_bitrix_url(url: str | None) -> str:
    if not url:
        return ""
    redacted = _REST_TOKEN_RE.sub(r"\1***/***", url)
    return redacted


def sanitize_bitrix_text(text: str | None) -> str:
    if not text:
        return ""
    return _TOKEN_FRAGMENT_RE.sub(r"\1***/***/", _REST_TOKEN_RE.sub(r"\1***/***", text))


def webhook_configured_label(webhook_url: str | None) -> str:
    return "configured=true" if (webhook_url or "").strip() else "configured=false"

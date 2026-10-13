"""Redact Avito secrets from URLs, headers, and log/error text."""

from __future__ import annotations

import re

_BEARER_RE = re.compile(r"(Bearer\s+)([A-Za-z0-9._\-+/=]{8,})", re.IGNORECASE)
_ACCESS_TOKEN_JSON_RE = re.compile(
    r'("(?:access_token|refresh_token|client_secret)"\s*:\s*")([^"]+)"',
    re.IGNORECASE,
)
_CLIENT_SECRET_QS_RE = re.compile(
    r"((?:client_secret|access_token|refresh_token)=)([^&\s\"']+)",
    re.IGNORECASE,
)
_LONG_TOKEN_RE = re.compile(r"\b([A-Za-z0-9]{32,})\b")


def sanitize_avito_text(text: str | None) -> str:
    if not text:
        return ""
    out = _BEARER_RE.sub(r"\1***", text)
    out = _ACCESS_TOKEN_JSON_RE.sub(r'\1***"', out)
    out = _CLIENT_SECRET_QS_RE.sub(r"\1***", out)
    return out


def sanitize_avito_url(url: str | None) -> str:
    if not url:
        return ""
    return sanitize_avito_text(url)


def credentials_configured_label(*, client_id: str | None, client_secret: str | None) -> str:
    ok = bool((client_id or "").strip() and (client_secret or "").strip())
    return "configured=true" if ok else "configured=false"


def mask_id(value: str | int | None, *, keep: int = 2) -> str:
    if value is None:
        return ""
    s = str(value)
    if len(s) <= keep * 2:
        return "***"
    return f"{s[:keep]}…{s[-keep:]}"

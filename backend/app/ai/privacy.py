"""What may leave the server: aliases instead of names, texts without contacts."""

from __future__ import annotations

import re
from typing import Any

# 10+ digits: phones; amounts like «12 500 000» (8 digits) stay
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\s\-()]*){9,}\d")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
HANDLE_RE = re.compile(r"(?<!\w)@\w{3,}")
ALIAS_RE = re.compile(r"(Менеджер|Avito)-(\d+)")


def manager_alias(manager_id: int) -> str:
    return f"Менеджер-{manager_id}"


def account_alias(account_id: int) -> str:
    return f"Avito-{account_id}"


def scrub(text: str, limit: int = 600) -> str:
    """Remove contacts and links; long texts are cut (the model needs the gist, not the archive)."""
    text = URL_RE.sub("[ссылка]", text)
    text = EMAIL_RE.sub("[email]", text)
    text = PHONE_RE.sub("[телефон]", text)
    text = HANDLE_RE.sub("[контакт]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def restore(value: Any, names: dict[str, str]) -> Any:
    """Put real names back into the model's answer (only in what the panel shows)."""
    if isinstance(value, str):
        return ALIAS_RE.sub(lambda m: names.get(m.group(0), m.group(0)), value)
    if isinstance(value, list):
        return [restore(v, names) for v in value]
    if isinstance(value, dict):
        return {k: restore(v, names) for k, v in value.items()}
    return value

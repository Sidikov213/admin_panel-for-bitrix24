"""Avito multi-account credentials from environment (never persisted)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AvitoAccountCredentials:
    slot: int
    name: str
    client_id: str
    client_secret: str
    enabled: bool = True

    @property
    def configured(self) -> bool:
        return bool(self.client_id.strip() and self.client_secret.strip())

    @property
    def credential_key(self) -> str:
        """Logical key for secret store mapping — not the secret itself."""
        return f"AVITO_ACCOUNT_{self.slot}"


_SLOT_RE = re.compile(r"^AVITO_ACCOUNT_(\d+)_CLIENT_ID$", re.IGNORECASE)


def load_avito_accounts_from_env(environ: dict[str, str] | None = None) -> list[AvitoAccountCredentials]:
    env = environ if environ is not None else dict(os.environ)
    slots: set[int] = set()
    for key in env:
        m = _SLOT_RE.match(key.strip())
        if m:
            slots.add(int(m.group(1)))

    # Legacy single-account aliases → slot 1
    if env.get("AVITO_CLIENT_ID") or env.get("AVITO_CLIENT_SECRET"):
        slots.add(1)

    accounts: list[AvitoAccountCredentials] = []
    for slot in sorted(slots):
        prefix = f"AVITO_ACCOUNT_{slot}_"
        client_id = (env.get(f"{prefix}CLIENT_ID") or "").strip()
        client_secret = (env.get(f"{prefix}CLIENT_SECRET") or "").strip()
        if slot == 1:
            client_id = client_id or (env.get("AVITO_CLIENT_ID") or "").strip()
            client_secret = client_secret or (env.get("AVITO_CLIENT_SECRET") or "").strip()
        name = (env.get(f"{prefix}NAME") or f"account_{slot}").strip()
        enabled_raw = (env.get(f"{prefix}ENABLED") or "true").strip().lower()
        enabled = enabled_raw not in {"0", "false", "no", "off"}
        accounts.append(
            AvitoAccountCredentials(
                slot=slot,
                name=name,
                client_id=client_id,
                client_secret=client_secret,
                enabled=enabled,
            )
        )
    return accounts


def conceptual_multi_account_model() -> dict:
    """Design-only model for 4+ accounts (Phase 1 — not persisted)."""
    return {
        "avito_accounts": [
            {
                "id": "internal UUID",
                "name": "human label",
                "enabled": True,
                "external_user_id": "Avito numeric user_id after first auth",
                "credential_key": "AVITO_ACCOUNT_N (env / secret store)",
                "last_sync_at": None,
            }
        ],
        "secrets_policy": "client_id/client_secret stay in env/secret storage only; never DB plaintext",
    }

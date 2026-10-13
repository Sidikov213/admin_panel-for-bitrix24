"""Avito integration — Phase 1 READ-ONLY probe client."""

from app.integrations.avito.client import AvitoClientError, AvitoReadOnlyClient
from app.integrations.avito.config import AvitoAccountCredentials, load_avito_accounts_from_env

__all__ = [
    "AvitoClientError",
    "AvitoReadOnlyClient",
    "AvitoAccountCredentials",
    "load_avito_accounts_from_env",
]

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: str) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/focus_analytics"
    BITRIX_WEBHOOK_URL: str = ""
    BITRIX_PORTAL_URL: str = ""
    # Stored as CSV string so pydantic-settings does not JSON-decode env values
    BITRIX_CATEGORY_IDS: str = "1,39"
    SYNC_INTERVAL_MINUTES: int = 5
    SYNC_OVERLAP_MINUTES: int = 10
    FULL_RECONCILE_HOURS: int = 24
    SESSION_SECRET: str = "change-me-in-production"
    COOKIE_SECURE: bool = False
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    APP_TIMEZONE: str = "Europe/Moscow"
    DEMO_MODE: bool = False

    SESSION_COOKIE_NAME: str = "focus_session"
    CSRF_COOKIE_NAME: str = "focus_csrf"
    SESSION_TTL_HOURS: int = 24 * 7
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15

    BITRIX_RATE_LIMIT_RPS: float = 2.0
    BITRIX_RETRY_MAX: int = 5
    BITRIX_REQUEST_TIMEOUT: float = 30.0

    # Manager Control — Timeman collector (READ ONLY timeman.status)
    TIMEMAN_COLLECTOR_ENABLED: bool = True
    TIMEMAN_MAX_MANAGERS_PER_CYCLE: int = 50
    TIMEMAN_REQUEST_TIMEOUT: float = 20.0
    TIMEMAN_RETRY_MAX: int = 3

    @field_validator("BITRIX_CATEGORY_IDS", mode="before")
    @classmethod
    def normalize_category_ids(cls, v: object) -> str:
        if v is None or v == "":
            return "1,39"
        if isinstance(v, list):
            return ",".join(str(int(x)) for x in v)
        return str(v)

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def normalize_cors(cls, v: object) -> str:
        if v is None or v == "":
            return "http://localhost:3000,http://127.0.0.1:3000"
        if isinstance(v, list):
            return ",".join(str(x) for x in v)
        return str(v)

    @property
    def bitrix_category_ids(self) -> list[int]:
        parts = _split_csv(self.BITRIX_CATEGORY_IDS)
        return [int(x) for x in parts] if parts else [1, 39]

    @property
    def cors_origins(self) -> list[str]:
        parts = _split_csv(self.CORS_ORIGINS)
        return parts or ["http://localhost:3000", "http://127.0.0.1:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()

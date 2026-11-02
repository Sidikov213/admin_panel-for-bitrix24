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

    # Daily digest to Telegram. Empty token → digest disabled.
    TELEGRAM_BOT_TOKEN: str = ""
    # Team/head chat for the summary digest (numeric id or @channel)
    TELEGRAM_CHAT_ID: str = ""
    DIGEST_ENABLED: bool = True
    # HH:MM in APP_TIMEZONE
    DIGEST_TIME: str = "09:00"
    # APScheduler cron day_of_week syntax
    DIGEST_DAYS: str = "mon-fri"
    # Open deal counts as "not moving" after this many days without observed movement
    DIGEST_STALE_DAYS: int = 7
    # Max deals listed per section
    DIGEST_TOP_N: int = 5

    @field_validator("DIGEST_TIME")
    @classmethod
    def validate_digest_time(cls, v: str) -> str:
        hour, _, minute = v.partition(":")
        if not (hour.isdigit() and minute.isdigit() and 0 <= int(hour) < 24 and 0 <= int(minute) < 60):
            raise ValueError("DIGEST_TIME must be HH:MM")
        return f"{int(hour):02d}:{int(minute):02d}"

    @property
    def telegram_configured(self) -> bool:
        return bool(self.TELEGRAM_BOT_TOKEN.strip())

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

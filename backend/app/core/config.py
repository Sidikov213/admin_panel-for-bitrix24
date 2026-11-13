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
    # Local hours (APP_TIMEZONE) in which the long full reconcile may start; empty = any time
    FULL_RECONCILE_WINDOW: str = "00:00-06:00"
    # The panel warns that the numbers are old when deals were not synced for this long
    STALE_SYNC_MINUTES: int = 120
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

    # Sales team working calendar (APP_TIMEZONE): stage deadlines in working hours skip
    # nights, weekends and the company-wide vacation
    WORK_DAYS: str = "mon-fri"
    WORK_HOURS: str = "09:00-17:00"
    # Yearly recurring MM-DD..MM-DD ranges, comma-separated (range may wrap the new year)
    COMPANY_HOLIDAYS: str = "12-26..01-11"

    # Daily / weekly report (ТЗ §11–12): stored in the panel archive, sent to Telegram
    REPORTS_ENABLED: bool = True
    # Working days only (WORK_DAYS minus COMPANY_HOLIDAYS), HH:MM in APP_TIMEZONE
    REPORT_DAILY_TIME: str = "20:00"
    # Weekly report about the previous Mon–Sun week
    REPORT_WEEKLY_DAY: str = "mon"
    REPORT_WEEKLY_TIME: str = "09:00"
    # Personal chats of the recipients (Максим, Андрей), comma-separated; empty → TELEGRAM_CHAT_ID
    TELEGRAM_REPORT_CHAT_IDS: str = ""
    REPORT_TOP_N: int = 7

    # Avito (read-only): JSON list of {"id": <Avito user id>, "name": "...", "client_id": "...",
    # "client_secret": "..."} — one pair per account from «Для профессионалов → API»
    AVITO_ACCOUNTS: str = ""
    AVITO_SYNC_INTERVAL_MINUTES: int = 5
    # First sync looks back this many days; later syncs are incremental by chat update time
    AVITO_INITIAL_DAYS: int = 30
    # First-reply norm in working minutes (regulations: a new lead is taken within 30 min)
    AVITO_REPLY_NORM_MINUTES: int = 30
    AVITO_RATE_LIMIT_RPS: float = 2.0

    # AI conclusions (ТЗ §9–11) via the Claude API. Empty key → AI is off, nothing leaves the server.
    ANTHROPIC_API_KEY: str = ""
    AI_MODEL: str = "claude-opus-5-5"
    # low | medium | high | xhigh | max — depth of the model's reasoning, and its cost
    AI_EFFORT: str = "medium"
    # By default only numbers go out: managers as «Менеджер-<id>», no clients, titles or links.
    # true → also comment and Avito texts (phones, e-mails and links removed) — needs the
    # company's consent to pass client correspondence to an external service.
    AI_SEND_TEXTS: bool = False
    # Add the AI conclusion to the scheduled daily / weekly report
    AI_REPORTS: bool = True
    # Cost guard: model calls per calendar day (manual runs and reports together)
    AI_DAILY_LIMIT: int = 30
    # Sales script / answer standards to check against (when the script is ready)
    AI_SALES_SCRIPT: str = ""
    AI_TIMEOUT_SECONDS: float = 180.0

    @property
    def ai_configured(self) -> bool:
        return bool(self.ANTHROPIC_API_KEY.strip())

    @field_validator("AI_EFFORT")
    @classmethod
    def validate_ai_effort(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("low", "medium", "high", "xhigh", "max"):
            raise ValueError("AI_EFFORT must be low, medium, high, xhigh or max")
        return v

    @property
    def avito_accounts(self) -> list[dict]:
        """Validated accounts. Secrets stay in the environment, never in the database."""
        import json

        if not self.AVITO_ACCOUNTS.strip():
            return []
        try:
            raw = json.loads(self.AVITO_ACCOUNTS)
        except json.JSONDecodeError as e:
            raise ValueError("AVITO_ACCOUNTS must be a JSON list") from e
        out = []
        for a in raw if isinstance(raw, list) else []:
            if not all(str(a.get(k, "")).strip() for k in ("id", "client_id", "client_secret")):
                raise ValueError("each AVITO_ACCOUNTS entry needs id, client_id, client_secret")
            out.append(
                {
                    "id": int(a["id"]),
                    "name": str(a.get("name") or a["id"]),
                    "client_id": str(a["client_id"]),
                    "client_secret": str(a["client_secret"]),
                }
            )
        return out

    @field_validator("REPORT_DAILY_TIME", "REPORT_WEEKLY_TIME")
    @classmethod
    def validate_report_time(cls, v: str) -> str:
        hour, _, minute = v.partition(":")
        if not (hour.isdigit() and minute.isdigit() and 0 <= int(hour) < 24 and 0 <= int(minute) < 60):
            raise ValueError("report time must be HH:MM")
        return f"{int(hour):02d}:{int(minute):02d}"

    @property
    def report_chat_ids(self) -> list[str]:
        ids = [x.strip() for x in self.TELEGRAM_REPORT_CHAT_IDS.split(",") if x.strip()]
        return ids or ([self.TELEGRAM_CHAT_ID.strip()] if self.TELEGRAM_CHAT_ID.strip() else [])

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

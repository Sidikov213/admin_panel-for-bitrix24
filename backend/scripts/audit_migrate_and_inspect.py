"""Apply migrations against audit Postgres and print table inventory."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/focus_analytics",
)


def migrate() -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = URL
    env.setdefault("SESSION_SECRET", "audit-session-secret-32chars-min")
    env.setdefault("CORS_ORIGINS", "http://localhost:13000")
    env.setdefault("BITRIX_WEBHOOK_URL", "")
    env.setdefault("DEMO_MODE", "false")
    subprocess.check_call([sys.executable, "-m", "alembic", "upgrade", "head"], env=env)
    subprocess.check_call([sys.executable, "-m", "alembic", "current"], env=env)
    subprocess.check_call([sys.executable, "-m", "alembic", "heads"], env=env)


async def inspect_tables() -> None:
    expected = [
        "users",
        "sessions",
        "login_attempts",
        "crm_managers",
        "crm_pipelines",
        "crm_stages",
        "crm_deals",
        "crm_activities",
        "deal_snapshots",
        "deal_change_events",
        "sync_runs",
        "sync_state",
        "sales_targets",
        "analytics_daily",
        "alembic_version",
    ]
    engine = create_async_engine(URL)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1")
        )
        tables = [r[0] for r in rows]
        print("TABLES", tables)
        missing = [t for t in expected if t not in tables and t != "alembic_version"]
        print("MISSING_REQUIRED", missing)
        for t in expected:
            if t not in tables:
                continue
            cols = await conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=:t ORDER BY 1"
                ),
                {"t": t},
            )
            print(f"COLS {t}:", [(c[0], c[1], c[2]) for c in cols])
        idx = await conn.execute(
            text(
                "SELECT tablename, indexname FROM pg_indexes "
                "WHERE schemaname='public' ORDER BY 1,2"
            )
        )
        print("INDEXES", [(r[0], r[1]) for r in idx])
    await engine.dispose()


if __name__ == "__main__":
    migrate()
    asyncio.run(inspect_tables())

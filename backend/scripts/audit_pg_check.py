"""Clean-DB table check for Stage 1 audit (PostgreSQL)."""

import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

EXPECTED = [
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
]


async def main() -> int:
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5433/focus_analytics",
    )
    eng = create_async_engine(url)
    async with eng.connect() as c:
        r = await c.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1")
        )
        tables = [row[0] for row in r]
        print("TABLES", tables)
        missing = [t for t in EXPECTED if t not in tables]
        print("MISSING", missing)
        try:
            ver = (await c.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            print("ALEMBIC", ver)
        except Exception as e:
            print("ALEMBIC_ERROR", type(e).__name__, e)
            return 1
        # sample indexes / uniques
        idx = await c.execute(
            text(
                "SELECT indexname FROM pg_indexes WHERE schemaname='public' "
                "AND tablename IN ('crm_deals','crm_activities','deal_snapshots') "
                "ORDER BY 1"
            )
        )
        print("INDEXES", [row[0] for row in idx])
    await eng.dispose()
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

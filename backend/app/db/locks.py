"""Session advisory locks held on a dedicated connection across commits."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession


class AdvisoryLock:
    def __init__(self, session: AsyncSession, key: int):
        self.session = session
        self.key = key
        self.connection: AsyncConnection | None = None

    async def acquire(self) -> bool:
        if self.session.get_bind().dialect.name != "postgresql":
            return True
        bind = self.session.bind
        engine = bind.engine if isinstance(bind, AsyncConnection) else bind
        self.connection = await engine.connect()
        try:
            acquired = bool((await self.connection.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": self.key}
            )).scalar())
            if not acquired:
                await self.connection.close()
                self.connection = None
            return acquired
        except BaseException:
            await self.connection.invalidate()
            await self.connection.close()
            self.connection = None
            raise

    async def release(self) -> None:
        conn, self.connection = self.connection, None
        if conn is None:
            return
        try:
            await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": self.key})
        except BaseException:
            # Never return a potentially locked connection to the pool.
            await conn.invalidate()
            raise
        finally:
            await conn.close()

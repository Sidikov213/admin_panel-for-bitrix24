"""Send the daily digest: summary to the team chat, personal lists to managers."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.timezone import utc_now
from app.notifications.digest import build_digest, render_manager_digest, render_team_digest
from app.notifications.telegram import TelegramClient, TelegramError
from app.repositories.sync import SyncRepository

logger = logging.getLogger(__name__)

LAST_DIGEST_STATE = "last_digest"


async def send_daily_digest(
    session: AsyncSession,
    *,
    force: bool = False,
    client: TelegramClient | None = None,
) -> dict[str, Any]:
    """Send today's digest once. `force` re-sends (manual "send now" from the panel)."""
    settings = get_settings()
    if not settings.telegram_configured:
        return {"status": "skipped", "reason": "telegram_not_configured"}

    repo = SyncRepository(session)
    digest = await build_digest(session)
    day = digest.day.isoformat()
    last = await repo.get_state(LAST_DIGEST_STATE) or {}
    if not force and last.get("date") == day:
        return {"status": "skipped", "reason": "already_sent_today", "date": day}

    client = client or TelegramClient(settings.TELEGRAM_BOT_TOKEN)
    errors: list[str] = []
    team_sent = False
    if settings.TELEGRAM_CHAT_ID.strip():
        try:
            await client.send_message(settings.TELEGRAM_CHAT_ID.strip(), render_team_digest(digest))
            team_sent = True
        except TelegramError as e:
            errors.append(f"team: {e}")
            logger.warning("digest_team_send_failed err=%s", e)

    managers_sent = 0
    for m in digest.managers_all:
        if not m.telegram_chat_id:
            continue
        try:
            await client.send_message(m.telegram_chat_id, render_manager_digest(digest, m))
            managers_sent += 1
        except TelegramError as e:
            errors.append(f"manager {m.manager_id}: {e}")
            logger.warning("digest_manager_send_failed manager_id=%s err=%s", m.manager_id, e)

    delivered = team_sent or managers_sent > 0
    if delivered:
        await repo.set_state(
            LAST_DIGEST_STATE,
            {
                "date": day,
                "at": utc_now().isoformat(),
                "team_sent": team_sent,
                "managers_sent": managers_sent,
                "errors": len(errors),
            },
        )
        await session.commit()
    result = {
        "status": "sent" if delivered else "failed" if errors else "skipped",
        "date": day,
        "team_sent": team_sent,
        "managers_sent": managers_sent,
        "errors": errors,
    }
    if not delivered and not errors:
        result["reason"] = "no_recipients"
    logger.info(
        "digest_done status=%s team_sent=%s managers_sent=%s errors=%s",
        result["status"],
        team_sent,
        managers_sent,
        len(errors),
    )
    return result

"""Pull Avito dialogs of every configured account and link them to Bitrix deals."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.timezone import utc_now
from app.integrations.avito.client import AvitoClient, AvitoError
from app.models.avito import AvitoChat, AvitoMessage
from app.models.crm import CrmDeal, DealComment
from app.models.sync import SyncStatus, SyncType
from app.repositories.sync import SyncRepository

logger = logging.getLogger(__name__)

STATE_KEY = "avito_sync"
OVERLAP = timedelta(minutes=10)
MAX_CHAT_PAGES = 50
MAX_MESSAGE_PAGES = 5
PAGE = 100
# Avito chat ids look like «u2i-AbC123~XyZ»; the regulations require the chat link in the deal
CHAT_ID_RE = re.compile(r"u2[iu]-[A-Za-z0-9_~\-]{6,}")
TYPE_PLACEHOLDERS = {"image": "[изображение]", "voice": "[голосовое сообщение]", "call": "[звонок]",
                     "file": "[файл]", "location": "[геолокация]", "item": "[объявление]", "link": "[ссылка]"}


def to_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def message_text(raw: dict[str, Any]) -> str:
    content = raw.get("content") or {}
    text = content.get("text") if isinstance(content, dict) else None
    if text:
        return str(text)[:20000]
    if isinstance(content, dict) and isinstance(content.get("link"), dict):
        return str(content["link"].get("text") or content["link"].get("url") or "[ссылка]")
    return TYPE_PLACEHOLDERS.get(str(raw.get("type") or ""), "")


def _apply_chat(chat: AvitoChat, raw: dict[str, Any], account_id: int) -> None:
    chat.account_id = account_id
    chat.created = to_dt(raw.get("created")) or chat.created
    chat.updated = to_dt(raw.get("updated")) or chat.updated
    context = raw.get("context") or {}
    chat.chat_type = str(context.get("type") or "") or chat.chat_type
    item = context.get("value") if isinstance(context.get("value"), dict) else {}
    if item:
        chat.item_id = int(item["id"]) if str(item.get("id") or "").isdigit() else chat.item_id
        chat.item_title = str(item.get("title") or "")[:512] or chat.item_title
        chat.item_url = str(item.get("url") or "")[:1024] or chat.item_url
    for user in raw.get("users") or []:
        uid = user.get("id")
        if uid is not None and int(uid) != account_id:
            chat.client_user_id = int(uid)
            chat.client_name = str(user.get("name") or "")[:255] or None


async def recompute_chat(session: AsyncSession, chat: AvitoChat) -> None:
    """First client message, first reply after it, last message — from stored messages."""
    msgs = (
        await session.execute(
            select(AvitoMessage)
            .where(AvitoMessage.chat_id == chat.chat_id, AvitoMessage.is_system.is_(False))
            .order_by(AvitoMessage.created, AvitoMessage.id)
        )
    ).scalars().all()
    chat.messages_count = len(msgs)
    first_in = next((m for m in msgs if m.direction == "in"), None)
    chat.first_in_at = first_in.created if first_in else None
    reply = next((m for m in msgs if m.direction == "out" and first_in and m.created >= first_in.created), None)
    chat.first_reply_at = reply.created if reply else None
    chat.last_message_at = msgs[-1].created if msgs else None
    chat.last_direction = msgs[-1].direction if msgs else None


async def sync_account(session: AsyncSession, client: AvitoClient, *, since: datetime) -> dict[str, int]:
    chats_seen = messages_new = 0
    touched: list[AvitoChat] = []
    for page in range(MAX_CHAT_PAGES):
        rows = await client.list_chats(offset=page * PAGE, limit=PAGE)
        if not rows:
            break
        fresh = [r for r in rows if (to_dt(r.get("updated")) or utc_now()) >= since]
        for raw in fresh:
            cid = str(raw.get("id") or "")
            if not cid:
                continue
            chat = (await session.execute(select(AvitoChat).where(AvitoChat.chat_id == cid))).scalar_one_or_none()
            if chat is None:
                chat = AvitoChat(chat_id=cid, account_id=client.account_id)
                session.add(chat)
            _apply_chat(chat, raw, client.account_id)
            touched.append(chat)
            chats_seen += 1
        # Chats come most recently updated first: an older one means the rest are older too
        if len(fresh) < len(rows) or len(rows) < PAGE:
            break
    await session.flush()

    for chat in touched:
        known = set(
            (await session.execute(select(AvitoMessage.message_id).where(AvitoMessage.chat_id == chat.chat_id))).scalars()
        )
        for page in range(MAX_MESSAGE_PAGES):
            rows = await client.list_messages(chat.chat_id, offset=page * PAGE, limit=PAGE)
            if not rows:
                break
            reached_known = False
            for raw in rows:
                mid = str(raw.get("id") or "")
                created = to_dt(raw.get("created"))
                if not mid or created is None:
                    continue
                if mid in known:
                    reached_known = True
                    continue
                mtype = str(raw.get("type") or "")
                session.add(
                    AvitoMessage(
                        message_id=mid,
                        chat_id=chat.chat_id,
                        direction="out" if raw.get("direction") == "out" else "in",
                        author_id=int(raw["author_id"]) if str(raw.get("author_id") or "").isdigit() else None,
                        msg_type=mtype or None,
                        created=created,
                        text=message_text(raw),
                        is_system=mtype == "system" or str(raw.get("author_id")) == "0",
                    )
                )
                known.add(mid)
                messages_new += 1
            # Newest first: once we meet messages we already have, the older pages are stored too
            if reached_known or len(rows) < PAGE:
                break
        await session.flush()
        await recompute_chat(session, chat)
    await session.flush()
    return {"chats": chats_seen, "messages": messages_new}


async def link_deals(session: AsyncSession) -> int:
    """Attach dialogs to deals whose fields or comments contain the chat id / chat link."""
    unlinked = {
        c.chat_id: c
        for c in (await session.execute(select(AvitoChat).where(AvitoChat.deal_bitrix_id.is_(None)))).scalars()
    }
    if not unlinked:
        return 0
    found: dict[str, tuple[int, str]] = {}
    for bid, raw in (await session.execute(select(CrmDeal.bitrix_id, CrmDeal.raw).where(CrmDeal.raw.isnot(None)))).all():
        for cid in CHAT_ID_RE.findall(json.dumps(raw, ensure_ascii=False)):
            if cid in unlinked:
                found.setdefault(cid, (bid, "deal_field"))
    for bid, text in (await session.execute(select(DealComment.deal_bitrix_id, DealComment.text))).all():
        for cid in CHAT_ID_RE.findall(text or ""):
            if cid in unlinked:
                found.setdefault(cid, (bid, "comment"))
    for cid, (bid, source) in found.items():
        unlinked[cid].deal_bitrix_id = bid
        unlinked[cid].deal_link_source = source
    await session.flush()
    return len(found)


async def run_avito_sync(
    session: AsyncSession,
    *,
    accounts: list[dict[str, Any]] | None = None,
    client_factory: Callable[[dict[str, Any]], AvitoClient] = AvitoClient,
) -> dict[str, Any]:
    settings = get_settings()
    accounts = accounts if accounts is not None else settings.avito_accounts
    if not accounts:
        return {"status": "skipped", "reason": "not_configured"}
    repo = SyncRepository(session)
    if not await repo.try_advisory_lock(SyncType.avito):
        return {"status": "skipped", "reason": "locked"}
    run = await repo.start_run(SyncType.avito)
    await session.commit()
    run_id = run.id
    results: dict[str, Any] = {}
    errors: list[str] = []
    try:
        state = await repo.get_state(STATE_KEY) or {}
        for account in accounts:
            key = str(account["id"])
            started = utc_now()
            last = to_dt((state.get(key) or {}).get("at"))
            since = last - OVERLAP if last else started - timedelta(days=settings.AVITO_INITIAL_DAYS)
            try:
                counts = await sync_account(session, client_factory(account), since=since)
                state[key] = {"at": started.isoformat(), "name": account.get("name")}
                results[key] = counts
                await session.commit()
            except AvitoError as e:
                await session.rollback()
                errors.append(f"{account.get('name') or key}: {e}")
                results[key] = {"error": str(e), "kind": e.kind}
                logger.warning("avito_sync_failed account=%s kind=%s", key, e.kind)
        linked = await link_deals(session)
        await repo.set_state(STATE_KEY, state)
        run = await session.get(type(run), run_id)
        await repo.finish_run(
            run,
            status=SyncStatus.failed if errors and len(errors) == len(accounts) else SyncStatus.success,
            items_processed=sum(r.get("messages", 0) for r in results.values()),
            errors_count=len(errors),
            error_message="; ".join(errors) or None,
            cursor_info={"accounts": results, "linked": linked},
        )
        await session.commit()
        return {"status": "done", "accounts": results, "linked": linked, "errors": errors}
    except Exception as e:
        await session.rollback()
        logger.exception("avito_sync_crashed")
        run = await session.get(type(run), run_id)
        if run is not None:
            await repo.finish_run(run, status=SyncStatus.failed, items_processed=0, errors_count=1, error_message=str(e))
            await session.commit()
        raise
    finally:
        await repo.advisory_unlock(SyncType.avito)

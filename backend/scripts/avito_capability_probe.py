#!/usr/bin/env python3
"""Avito Phase 1 — CONTROLLED READ-ONLY capability probe.

Never prints secrets. Never sends messages. Never edits ads.
Never modifies Bitrix / FocusGroup SLA bot / Timeman / Sales Rules.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent if (BACKEND.parent / ".env").exists() else BACKEND
sys.path.insert(0, str(BACKEND))


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        key, val = k.strip(), v.strip().strip('"').strip("'")
        if key.startswith("AVITO_") or key in {"DATABASE_URL", "DEMO_MODE"}:
            os.environ[key] = val


for _p in (ROOT / ".env", BACKEND / ".env", Path("/app/.env")):
    _load_env_file(_p)

from app.integrations.avito.client import AvitoClientError, AvitoReadOnlyClient
from app.integrations.avito.config import conceptual_multi_account_model, load_avito_accounts_from_env
from app.integrations.avito.parse import (
    extract_top_level_keys,
    first_response_times,
    normalize_direction,
    parse_avito_timestamp,
)
from app.integrations.avito.sanitize import sanitize_avito_text


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sample_item(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw.get("id") or raw.get("item_id"),
        "title": raw.get("title") or raw.get("name"),
        "status": raw.get("status"),
        "category": (raw.get("category") or {}).get("name")
        if isinstance(raw.get("category"), dict)
        else raw.get("category"),
        "created": raw.get("start_time") or raw.get("created") or raw.get("created_at"),
        "url": raw.get("url") or raw.get("url_path"),
        "price": raw.get("price"),
        "keys_present": extract_top_level_keys(raw),
    }


def _sample_chat(raw: dict[str, Any]) -> dict[str, Any]:
    context = raw.get("context") if isinstance(raw.get("context"), dict) else {}
    value = context.get("value") if isinstance(context.get("value"), dict) else {}
    users = raw.get("users") if isinstance(raw.get("users"), list) else []
    return {
        "id": raw.get("id"),
        "created": raw.get("created"),
        "updated": raw.get("updated"),
        "unread": raw.get("unread") if "unread" in raw else raw.get("unread_count"),
        "item_id": value.get("id") or raw.get("item_id"),
        "item_title": value.get("title"),
        "users_count": len(users),
        "user_keys": extract_top_level_keys(users[0]) if users else [],
        "keys_present": extract_top_level_keys(raw),
        "context_type": context.get("type"),
    }


def _sample_message(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw.get("id"),
        "created": raw.get("created"),
        "direction": normalize_direction(raw.get("direction")),
        "direction_raw": raw.get("direction"),
        "author_id": raw.get("author_id") or raw.get("authorId"),
        "type": raw.get("type"),
        "has_content": bool(raw.get("content") or raw.get("message")),
        "keys_present": extract_top_level_keys(raw),
        "parsed_at": parse_avito_timestamp(raw.get("created")).isoformat()
        if parse_avito_timestamp(raw.get("created"))
        else None,
    }


async def probe_account(client: AvitoReadOnlyClient) -> dict[str, Any]:
    report: dict[str, Any] = {
        "account_name": client.account_name,
        "configured": client.configured_label,
        "authenticated": False,
        "methods_called": [],
        "auth": {},
        "account": {},
        "items": {},
        "chats": {},
        "messages": {},
        "response_time_sample": {},
        "errors": [],
        "rate_limits": {"events": 0, "retry_after": None},
        "pagination": {},
    }

    if not client.configured:
        report["errors"].append("credentials_not_configured")
        return report

    try:
        auth = await client.authenticate()
        report["authenticated"] = True
        report["auth"] = auth
        report["methods_called"].append("POST /token")
    except AvitoClientError as e:
        report["errors"].append(sanitize_avito_text(str(e)))
        return report

    # Account self
    try:
        self_info = await client.get_self()
        report["methods_called"].append("GET /core/v1/accounts/self")
        report["account"] = {
            "keys_present": extract_top_level_keys(self_info),
            "id": self_info.get("id") or (self_info.get("result") or {}).get("id"),
            "name": self_info.get("name") or (self_info.get("result") or {}).get("name"),
            "email_present": bool(self_info.get("email") or (self_info.get("result") or {}).get("email")),
            "phone_present": bool(self_info.get("phone") or (self_info.get("result") or {}).get("phone")),
            "raw_shape": "wrapped" if "result" in self_info else "flat",
        }
        user_id = report["account"]["id"]
    except AvitoClientError as e:
        report["errors"].append(f"account_self:{sanitize_avito_text(str(e))}")
        user_id = None

    # Items sample
    try:
        items_resp = await client.list_items(per_page=10, page=1)
        report["methods_called"].append("GET /core/v1/items")
        resources = items_resp.get("resources") or items_resp.get("items") or items_resp.get("result") or []
        if isinstance(resources, dict):
            resources = resources.get("items") or resources.get("list") or []
        if not isinstance(resources, list):
            resources = []
        report["items"] = {
            "count_returned": len(resources),
            "response_keys": extract_top_level_keys(items_resp),
            "sample": [_sample_item(x) for x in resources[:10] if isinstance(x, dict)],
            "pagination_hints": {
                k: items_resp.get(k)
                for k in ("page", "per_page", "pages", "total", "meta", "next")
                if k in items_resp
            },
        }
        report["pagination"]["items"] = report["items"]["pagination_hints"]
    except AvitoClientError as e:
        report["errors"].append(f"items:{sanitize_avito_text(str(e))}")

    # Chats + messages
    if user_id is not None:
        try:
            chats_resp = await client.list_chats(user_id, limit=10, offset=0)
            report["methods_called"].append("GET /messenger/v2/accounts/{user_id}/chats")
            chats = chats_resp.get("chats") or chats_resp.get("resources") or chats_resp.get("result") or []
            if isinstance(chats, dict):
                chats = chats.get("chats") or chats.get("list") or []
            if not isinstance(chats, list):
                chats = []
            chat_samples = [_sample_chat(c) for c in chats[:10] if isinstance(c, dict)]
            report["chats"] = {
                "count_returned": len(chats),
                "response_keys": extract_top_level_keys(chats_resp),
                "sample": chat_samples,
            }

            # One chat detail + messages
            if chats:
                chat_id = str(chats[0].get("id"))
                try:
                    detail = await client.get_chat(user_id, chat_id)
                    report["methods_called"].append(
                        "GET /messenger/v2/accounts/{user_id}/chats/{chat_id}"
                    )
                    report["chats"]["detail_keys"] = extract_top_level_keys(detail)
                except AvitoClientError as e:
                    report["errors"].append(f"chat_detail:{sanitize_avito_text(str(e))}")

                try:
                    msgs_resp = await client.list_messages(user_id, chat_id, limit=50, offset=0)
                    report["methods_called"].append(
                        "GET /messenger/v3/accounts/{user_id}/chats/{chat_id}/messages/"
                    )
                    messages = (
                        msgs_resp.get("messages")
                        or msgs_resp.get("resources")
                        or msgs_resp.get("result")
                        or []
                    )
                    if isinstance(messages, dict):
                        messages = messages.get("messages") or messages.get("list") or []
                    if not isinstance(messages, list):
                        messages = []
                    msg_samples = [_sample_message(m) for m in messages[:20] if isinstance(m, dict)]
                    report["messages"] = {
                        "count_returned": len(messages),
                        "response_keys": extract_top_level_keys(msgs_resp),
                        "sample": msg_samples,
                        "direction_values": sorted(
                            {
                                str(m.get("direction_raw"))
                                for m in msg_samples
                                if m.get("direction_raw") is not None
                            }
                        ),
                        "author_id_present": any(m.get("author_id") is not None for m in msg_samples),
                    }
                    report["response_time_sample"] = first_response_times(
                        [m for m in messages if isinstance(m, dict)]
                    )
                except AvitoClientError as e:
                    report["errors"].append(f"messages:{sanitize_avito_text(str(e))}")
        except AvitoClientError as e:
            report["errors"].append(f"chats:{sanitize_avito_text(str(e))}")

    report["rate_limits"] = {
        "events": client.rate_limit_events,
        "retry_after": client.last_retry_after,
        "retries": client.retry_count,
        "call_counts": dict(client.call_counts),
    }
    return report


def classify_gates(live: dict[str, Any]) -> dict[str, str]:
    auth_ok = bool(live.get("authenticated"))
    account = live.get("account") or {}
    items = live.get("items") or {}
    chats = live.get("chats") or {}
    messages = live.get("messages") or {}
    rt = live.get("response_time_sample") or {}

    ads = "YES" if items.get("count_returned", 0) > 0 else ("PARTIAL" if auth_ok and "items" in live else "NO")
    if auth_ok and items and items.get("count_returned", 0) == 0 and not any(
        "items:" in e for e in live.get("errors", [])
    ):
        ads = "PARTIAL"  # access ok, empty catalog

    chats_access = "YES" if chats.get("count_returned", 0) > 0 else (
        "PARTIAL" if auth_ok and "chats" in live and not any("chats:" in e for e in live.get("errors", [])) else "NO"
    )
    if any("chats:" in e for e in live.get("errors", [])):
        chats_access = "NO" if "403" in str(live.get("errors")) or "404" in str(live.get("errors")) else chats_access

    msgs_access = "YES" if messages.get("count_returned", 0) > 0 else (
        "PARTIAL" if messages else "NO"
    )

    first_resp = "YES" if rt.get("first_response_seconds") is not None else (
        "PARTIAL" if rt.get("customer_first_at") or messages.get("direction_values") else "NO"
    )
    sla = first_resp  # same fields enable SLA buckets

    # Manager attribution from Avito alone: author_id present but not Bitrix manager mapping
    author = bool(messages.get("author_id_present"))
    manager_attr = "PARTIAL" if author else "NO"
    if author and messages.get("direction_values"):
        # Still not Bitrix manager identity
        manager_attr = "PARTIAL"

    return {
        "AVITO_AUTH": "PASS" if auth_ok else "FAIL",
        "ACCOUNT_DATA": "AVAILABLE" if account.get("id") else ("PARTIAL" if auth_ok else "NO"),
        "ADS_ACCESS": ads,
        "CHATS_ACCESS": chats_access,
        "MESSAGES_ACCESS": msgs_access,
        "FIRST_RESPONSE_CALCULABLE": first_resp,
        "SLA_CALCULABLE": sla,
        "MANAGER_ATTRIBUTION": manager_attr,
    }


async def main() -> int:
    accounts = load_avito_accounts_from_env()
    out: dict[str, Any] = {
        "probe_at": _now(),
        "phase": "avito-phase1-probe",
        "read_only": True,
        "write_methods_used": False,
        "accounts_configured_slots": [a.slot for a in accounts if a.configured],
        "accounts_found": [
            {
                "slot": a.slot,
                "name": a.name,
                "configured": a.configured,
                "enabled": a.enabled,
                "credential_key": a.credential_key,
            }
            for a in accounts
        ],
        "live": None,
        "gates": {},
        "multi_account_design": conceptual_multi_account_model(),
        "policy": {
            "existing_sla_bot_modified": False,
            "bitrix_modified": False,
            "avito_write_methods_used": False,
        },
    }

    target = next((a for a in accounts if a.enabled and a.configured), None)
    if target is None:
        out["live"] = {
            "configured": "configured=false",
            "authenticated": False,
            "errors": ["no_avito_credentials_in_env"],
            "methods_called": [],
        }
        out["gates"] = classify_gates(out["live"])
    else:
        client = AvitoReadOnlyClient(target)
        live = await probe_account(client)
        out["live"] = live
        out["gates"] = classify_gates(live)

    docs = ROOT / "docs"
    if not docs.exists():
        docs = Path("/tmp")
    docs.mkdir(parents=True, exist_ok=True)
    json_path = docs / "avito-capability-probe-raw.json"
    path_payload = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    json_path.write_text(path_payload, encoding="utf-8")
    print(f"WROTE {json_path}")
    print(path_payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

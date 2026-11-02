"""Read-only probe of the Avito accounts in AVITO_ACCOUNTS.

For each account: is the token issued, does /core/v1/accounts/self match the id, is the
Messenger API available, what the chat and message objects look like. Prints only ids,
counts and field names — no client names, no message text, no secrets.

    docker compose exec backend python scripts/avito_probe.py
"""

import asyncio
import sys

sys.path.insert(0, ".")

from app.core.config import get_settings  # noqa: E402
from app.integrations.avito.client import AvitoClient, AvitoError  # noqa: E402


async def probe(account: dict) -> bool:
    print(f"\n== {account['name']} (id {account['id']})")
    client = AvitoClient(account)
    try:
        me = await client.self_info()
        same = str(me.get("id")) == str(account["id"])
        print(f"token: ok · accounts/self id={me.get('id')} {'matches' if same else 'DOES NOT MATCH the configured id'}")
    except AvitoError as e:
        print(f"token / profile: FAILED kind={e.kind} {e}")
        return False
    try:
        chats = await client.list_chats(limit=5)
        print(f"messenger chats: {len(chats)} on the first page")
        if chats:
            c = chats[0]
            print(f"  chat fields: {sorted(c.keys())}")
            print(f"  context type: {(c.get('context') or {}).get('type')}, created type: {type(c.get('created')).__name__}")
            msgs = await client.list_messages(str(c["id"]), limit=5)
            print(f"  messages: {len(msgs)}; fields: {sorted(msgs[0].keys()) if msgs else '—'}")
            if msgs:
                print(f"  directions: {sorted({m.get('direction') for m in msgs})}, types: {sorted({m.get('type') for m in msgs})}")
                if len(msgs) >= 2:
                    print(f"  newest first: {msgs[0].get('created', 0) >= msgs[-1].get('created', 0)}")
        return True
    except AvitoError as e:
        print(f"messenger: FAILED kind={e.kind} {e}")
        return False


async def main() -> int:
    try:
        accounts = get_settings().avito_accounts
    except ValueError as e:
        print(f"AVITO_ACCOUNTS is invalid: {e}")
        return 2
    if not accounts:
        print("AVITO_ACCOUNTS is empty")
        return 2
    results = [await probe(a) for a in accounts]
    print(f"\nRESULT: {sum(results)}/{len(results)} accounts ok")
    return 0 if all(results) else 1


sys.exit(asyncio.run(main()))

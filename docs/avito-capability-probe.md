# Avito Phase 1 — Capability Probe (READ ONLY)

**Date:** 2026-10-11  
**Branch:** `avito-phase1-probe` (from `focus-analytics-v1` / `dc1eb8f`)  
**Scope:** Probe only — no UI, no full sync, no Avito writes, no Bitrix writes, no SLA-bot changes.

---

## Executive summary

Isolated Avito READ-ONLY client + probe tooling was implemented and unit-tested.  
**Live Avito API authentication was not executed** because no Avito credentials are present in local `.env`.

Bitrix-side investigation (local Focus Analytics DB) found **strong Open Lines / Avito connector evidence**, supporting a **hybrid** analytics design.

---

## Security

| Check | Result |
|---|---|
| Credentials source | `.env` only (`AVITO_ACCOUNT_N_*`) |
| Secrets printed/logged | No |
| Secrets tracked by Git | No |
| `.env.example` placeholders | Yes (empty values) |

Expected env shape:

```env
AVITO_ACCOUNT_1_NAME=
AVITO_ACCOUNT_1_CLIENT_ID=
AVITO_ACCOUNT_1_CLIENT_SECRET=
AVITO_ACCOUNT_1_ENABLED=true
```

Legacy aliases `AVITO_CLIENT_ID` / `AVITO_CLIENT_SECRET` map to slot 1.

---

## Code delivered (isolated)

| Path | Role |
|---|---|
| `backend/app/integrations/avito/client.py` | READ-ONLY allow-listed HTTP client |
| `backend/app/integrations/avito/config.py` | Multi-account env loader + design model |
| `backend/app/integrations/avito/sanitize.py` | Token/secret redaction |
| `backend/app/integrations/avito/parse.py` | Timestamps, direction, first-response |
| `backend/scripts/avito_capability_probe.py` | Live probe runner |
| `backend/scripts/avito_bitrix_link_probe.py` | Bitrix link evidence (DB RO) |
| `backend/tests/test_avito_client.py` | Unit tests (fixtures only) |

**Allow-listed reads only:**

- `POST /token` (auth)
- `GET /core/v1/accounts/self`
- `GET /core/v1/items`
- `GET /messenger/v2/accounts/{user_id}/chats`
- `GET /messenger/v2/accounts/{user_id}/chats/{chat_id}`
- `GET /messenger/v3/accounts/{user_id}/chats/{chat_id}/messages/`

**Blocked by policy:** send/delete messages, mark-as-read, blacklist, webhooks, uploads, item edits.

---

## Live Avito methods actually called

| Method | Called? | Result |
|---|---|---|
| `POST https://api.avito.ru/token` | No | `configured=false` — credentials missing |
| Account / items / chats / messages | No | Skipped |

Raw output: `docs/avito-capability-probe-raw.json`

```
configured=false
authenticated=false
errors=["no_avito_credentials_in_env"]
```

### How to re-run live probe (after adding secrets to local `.env`)

```bash
docker compose build backend
docker compose exec -e PYTHONPATH=/app backend python scripts/avito_capability_probe.py
```

Do not commit `.env`.

---

## Documented API capabilities (official catalog; not yet live-verified)

From Avito Business API (OpenAPI / developer docs):

| Area | Endpoint family | Notes |
|---|---|---|
| Auth | `POST /token` client_credentials | Typical `expires_in` ~86400; Bearer token |
| Account | `GET /core/v1/accounts/self` | Numeric `user_id` for messenger paths |
| Items | `GET /core/v1/items` | Pagination `page` / `per_page` |
| Chats | `GET /messenger/v2/.../chats` | Includes item context, unread, users |
| Messages | `GET /messenger/v3/.../messages/` | Fields include `created` (unix), `direction` (`in`/`out`), `author_id` |
| Send message | `POST /messenger/v1/.../messages` | **Not used** (write) |

Messenger API availability depends on Avito subscription tier (docs: Максимальный / Расширенный by vertical).

---

## Response-time feasibility (from schema + parse helpers)

| Metric | Status | Basis |
|---|---|---|
| Customer first message T1 | AVAILABLE* | `direction=in` + `created` |
| Manager first reply T2 | AVAILABLE* | first `direction=out` after T1 |
| First response T2−T1 | AVAILABLE* | computed in `first_response_times()` |
| Unanswered chats | AVAILABLE* | no `out` after last `in` / chat-level unread |
| SLA 15 / 30 / 60 min | AVAILABLE* | buckets on T2−T1 |
| Median / average response | AVAILABLE* | aggregate over chats |
| By account | AVAILABLE* | per credential slot / `user_id` |
| By listing | AVAILABLE* | chat `context.value.id` (item) |

\* **AVAILABLE pending live confirmation** that message payloads include `direction` + `created` for this account/tariff.

Unit tests cover timestamp/direction/first-response parsing with sanitized fixtures.

---

## Manager attribution

| Source | Classification | Notes |
|---|---|---|
| Direct Avito API | **PARTIAL** | `author_id` identifies Avito user/employee id — **not** Bitrix manager |
| Bitrix Open Lines | **PARTIAL → strong for ops** | Activity `RESPONSIBLE_ID` + subject labels managers; live subjects show names like «Авитологи» / WhatsApp lines |
| Invented mapping | Forbidden | Not done |

**Verdict:** Avito alone is **not DIRECT** for CRM manager identity. Bitrix Open Lines is the practical manager source.

---

## Bitrix deal link (live DB evidence)

Probe: `docs/avito-bitrix-link-probe.json` (+ SQL follow-up).

| Match key | Strength | Live evidence |
|---|---|---|
| `SOURCE_ID` contains `AVITO` / `AVITOCONNECTOR` | **STRONG_HEURISTIC** | `SOURCE_ID=75\|AVITOCONNECTOR` on deal snapshots; **6 distinct deals** in cat 1/39 |
| Open Line activity subject `(Avito)` / «Авито» | **STRONG_HEURISTIC** | **640** activities with Avito markers; type_id=6 (Open Line chat) |
| Deal title contains «Авито»/Avito | **WEAK_HEURISTIC** | **625 / 1855** deals in cat 1+39 (text only — not deterministic) |
| Snapshot `COMMENTS` mentioning Avito | Weak auxiliary | Present but free-text |
| Stable Avito chat_id / item_id in CRM fields | **Not proven DIRECT** | Need UF_*/ORIGIN_ID inspection + live Avito ids |

**Classification: STRONG_HEURISTIC** (not DIRECT yet).

Customer name alone is **not** used as a deterministic key.

---

## Sales attribution chain feasibility

| Step | Status |
|---|---|
| Avito account | YES* (after auth / `accounts/self`) |
| Listing | YES* (`/core/v1/items` + chat item context) |
| Inquiry/chat | YES* (messenger v2/v3) |
| Bitrix deal | **PARTIAL** (Open Lines + `AVITOCONNECTOR`; needs stable id join) |
| Manager | **PARTIAL** (Bitrix responsible / OL) |
| WON/LOST | YES (existing Focus stage semantics) |
| Revenue | YES (existing `opportunity`) |

Future metrics:

| Metric | Feasibility |
|---|---|
| # Avito inquiries | YES* |
| Inquiry → deal | PARTIAL |
| Inquiry → WON | PARTIAL |
| Revenue from Avito | PARTIAL |
| Revenue per account / listing | PARTIAL / YES* |
| Response speed vs conversion/revenue | PARTIAL |

\* Pending live Avito access.

---

## Direct Avito vs Bitrix Open Lines vs Hybrid

| Need | Best source |
|---|---|
| Account / listing / raw messages / precise timestamps | **Direct Avito API** |
| Manager / deal / pipeline / WON-LOST / revenue | **Bitrix** |
| Current SLA bot path | Bitrix Open Lines (unchanged) |

**Recommendation: HYBRID**

1. Avito API → chats, messages, items, first-response SLA  
2. Bitrix → manager, deal, money  
3. Join via connector/`SOURCE_ID` + Open Line activity metadata; improve to DIRECT when chat/item ids are stored in CRM fields.

Do **not** replace the existing FocusGroup SLA bot in Phase 1.

---

## Multi-account architecture (design only)

```yaml
avito_accounts:
  - id: <uuid>
    name: <label>
    enabled: true
    external_user_id: <avito user_id>
    credential_key: AVITO_ACCOUNT_N   # env / secret store
    last_sync_at: null
```

- 4+ accounts via numbered env slots — no code change required for new slots.  
- Secrets never stored in DB plaintext.  
- No multi-account sync implemented in Phase 1.

**MULTI ACCOUNT ARCHITECTURE: READY** (config model + loader).

---

## Rate limits / pagination (observed)

| Topic | Observation |
|---|---|
| Live 429s | None (no live calls) |
| Client behavior | Retry with `Retry-After` / backoff; throttle ~0.35s |
| Items pagination | Docs: `page` / `per_page` |
| Chats/messages | Docs: `limit` / `offset` |
| History window | Not verified live |

**RATE LIMIT RISK: MEDIUM** (messenger + multi-account; keep small polls).

---

## Impact on current system

| Constraint | Status |
|---|---|
| Bitrix worker / Timeman / Sales Rules / Manager Control | Untouched |
| FocusGroup SLA bot / `/opt/prosrochka` | Untouched |
| VPS deploy | Not done |
| Avito write methods | Not used |

---

## Tests

```
pytest → 103 passed (includes 12 Avito unit tests)
```

Coverage: auth parsing, sanitization, pagination/retry 429, timeout, direction/timestamp, policy allow-list.

---

## Final gates

```
AVITO AUTH: FAIL
ACCOUNT DATA: NO
ADS ACCESS: NO
CHATS ACCESS: NO
MESSAGES ACCESS: NO

FIRST RESPONSE CALCULABLE: PARTIAL   # schema + parser ready; not live-verified
SLA CALCULABLE: PARTIAL
MANAGER ATTRIBUTION: PARTIAL         # Bitrix OL; Avito author_id only PARTIAL

BITRIX DEAL LINK: STRONG_HEURISTIC
SALES ATTRIBUTION: PARTIAL

MULTI ACCOUNT ARCHITECTURE: READY
RATE LIMIT RISK: MEDIUM

EXISTING SLA BOT MODIFIED: NO
BITRIX MODIFIED: NO
AVITO WRITE METHODS USED: NO

TESTS: PASS

READY FOR AVITO ANALYTICS V1: PARTIAL
```

### Blocker to upgrade AUTH / live YES

Add one account’s credentials to local gitignored `.env`:

```env
AVITO_ACCOUNT_1_NAME=primary
AVITO_ACCOUNT_1_CLIENT_ID=...
AVITO_ACCOUNT_1_CLIENT_SECRET=...
```

Re-run `scripts/avito_capability_probe.py`, then update this report with live field schemas.

---

**STOP after probe.** No Avito UI / full synchronization without explicit next confirmation.

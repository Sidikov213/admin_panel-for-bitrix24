# Bitrix Full Initial Sync Report

## Status: **PASS**

Controlled full initial sync for categories **1 (Сваи)** and **39 (Отложенный спрос)**.  
Bitrix: read-only. Scheduled worker: **not started**.

## Environment

| Key | Value |
|-----|-------|
| Portal | focushouse.bitrix24.ru |
| Webhook | configured=true (sanitized) |
| Sanitized base | `https://focushouse.bitrix24.ru/rest/***/***/` |
| Categories | `[1, 39]` |
| Database | `127.0.0.1:55432/focus_analytics` |
| Started (UTC) | 2026-10-06T11:01:10+00:00 |
| Finished (UTC) | 2026-10-06T11:42:27+00:00 |
| Duration (s) | **2477.38** (~41 min) |

## 1–2. Deal counts Bitrix vs PostgreSQL

| Category | Bitrix unique IDs | Bitrix total field | PostgreSQL | Match |
|----------|------------------:|-------------------:|-----------:|:-----:|
| 1 | 1472 | 1472 | 1472 | YES |
| 39 | 374 | 374 | 374 | YES |

**BITRIX COUNTS MATCH: YES**

## 3. Entity totals (PostgreSQL)

| Entity | Count |
|--------|------:|
| managers | 72 |
| pipelines | 2 |
| stages | 18 |
| deals | 1846 |
| activities | 16749 |
| snapshots | 1846 |
| change_events | 0 |

## 4–5. Discrepancies

No deal-count discrepancies.

Notes (not count mismatches):

- Activities sync `items_processed=24072` vs unique DB rows `16749`: Bitrix `crm.activity.list` pagination returned overlapping activity IDs; upserts are idempotent; **duplicate bitrix_id in DB = 0**.
- Skipped **7502** activities owned by deals outside categories 1/39 (controlled scope).
- `won + lost + active = 805 + 610 + 431 = 1846` (all deals classified).

## 6. Business signals (PostgreSQL)

| Signal | Count |
|--------|------:|
| active | 431 |
| won | 805 |
| lost | 610 |
| missing_from_bitrix | 0 |
| overdue activities | 157 |
| deals without future activity | 79 |

## 7. Sync runs

| type | status | items | errors | duration_s | notes |
|------|--------|------:|-------:|-----------:|-------|
| dictionaries | success | 92 | 0 | 124.05 | |
| full_reconcile | success | 1846 | 0 | 730.19 | seen=1846, missing_marked=0, cursor_advanced |
| activities | success | 24072 | 0 | 1068.25 | allowed_owners=1846, skipped_other_category=7502, cursor_advanced |

Client metrics:

- retries: **9** (all network timeouts; no HTTP 429)
- rate_limit_events (HTTP 429): **0**
- network_retries: **9**
- call_counts: `crm.deal.list=78`, `crm.activity.list=632`, `user.search=2`, `crm.dealcategory.list=1`, `crm.status.list=2`

## 8. Integrity checks

| Check | Result |
|-------|--------|
| duplicates (deals) | 0 |
| duplicates (activities) | 0 |
| webhook in report/logs artifact | PASS (sanitized only) |
| Bitrix write methods | none |
| methods used | crm.activity.list, crm.deal.list, crm.dealcategory.list, crm.status.list, user.search |
| last_deals_sync cursor | set (`2026-10-06T11:24:37Z`) |
| last_activities_sync cursor | set (`2026-10-06T11:42:25Z`) |
| last_full_reconcile | set (`2026-10-06T11:42:27Z`) |
| full reconcile status | success |

## 9. Tests

- pytest: **49 passed**
- frontend: not modified

## 10. Gates

- FULL INITIAL SYNC: **PASS**
- BITRIX COUNTS MATCH: **YES**
- DATABASE CONSISTENCY: **PASS**
- READY FOR SCHEDULED WORKER TEST: **YES**

Scheduled worker was **not** started.

Before starting the worker (after your confirmation): rebuild the worker Docker image so it includes `crm.status.list` semantics + `LAST_UPDATED` activity cursor.

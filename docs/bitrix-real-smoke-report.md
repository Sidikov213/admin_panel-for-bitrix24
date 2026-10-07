# Bitrix Real Smoke Report

## Status

**PASS** (smoke) + **fixes verified** (stage semantics + activity cursor)

Limited controlled smoke against real Bitrix24 (read-only). Full initial sync **not** executed.

## Environment

| Key | Value |
|-----|-------|
| Portal | focushouse.bitrix24.ru |
| Webhook | configured=true |
| Sanitized base | `https://focushouse.bitrix24.ru/rest/***/***/` |
| Categories | `[1, 39]` |
| DEMO_MODE | False |
| Database | `focus_analytics_bitrix_test` (isolated from audit/perf seed) |
| Worker | stopped during smoke / fix verify |

## Permissions

| Check | Result |
|-------|--------|
| Bitrix connection | PASS |
| CRM scope | PASS |
| User scope | PASS |

## REST methods (allow-list)

Static allow-list only. No write methods were called.

Added for Stage 1.5 fix: `crm.status.list` (read-only status dictionary with SEMANTICS).

## Pipelines discovered

| ID | name |
|----|------|
| 1 | Сваи |
| 39 | Отложенный спрос |

## Stage semantics fix (live-confirmed)

### Problem

`crm.dealcategory.stage.list` returns `SEMANTICS=null` for all stages in categories 1 and 39 → Focus Analytics stored null → `won_count=0` / `lost_count=0`.

### Live probe findings

| Source | Result |
|--------|--------|
| `crm.dealcategory.stage.list` | SEMANTICS always null |
| `crm.status.list` `ENTITY_ID=DEAL_STAGE_1` / `DEAL_STAGE_39` | SEMANTICS present for terminal stages (`S`/`F`) |
| `crm.deal.get` → `STAGE_SEMANTIC_ID` | Present on deals (`S`/`F`/`P`) |
| Stage display name | **Not** used as primary logic |

Probe artifact: `docs/bitrix-probe-semantics-activities.json`

### Implementation

1. Primary: `crm.status.list` during dictionary sync (`DEAL_STAGE_{category}`)
2. Overlay: deal `STAGE_SEMANTIC_ID` via `_ensure_stage_semantics`
3. Documented fallback: systemic `STATUS_ID` suffixes `:WON` / `:LOSE` / `:LOST` (not names)
4. Dictionary re-sync does **not** wipe non-null semantics when Bitrix returns null (process stages)

### Live re-verify gates

| Check | Result |
|-------|--------|
| C1:WON → success | PASS |
| C1:LOSE → failure | PASS |
| C39:WON → success | PASS |
| C39:LOSE → failure | PASS |
| Deal 8527 / C1:WON → won | PASS |
| Smoke KPI won_count / lost_count | **1 / 2** (was 0 / 0) |

Artifact: `docs/bitrix-fix-verify.json`

## Activity incremental cursor fix (live-confirmed)

### Problem

Stage 1 hardening used `>=DATE_MODIFY` for incremental activities, but live `crm.activity.list` samples show `DATE_MODIFY` absent/null. Filtering on a missing field is unsafe (ignored → oversized pulls).

### Live probe findings

| Check | Result |
|-------|--------|
| Field `LAST_UPDATED` present | yes (sample) |
| Field `DATE_MODIFY` present | no / null |
| Filter `>=LAST_UPDATED` | works |
| Order by `LAST_UPDATED` | works |
| Recommended cursor | **LAST_UPDATED** |

### Implementation

- Incremental activities: `>=LAST_UPDATED` with `SYNC_OVERLAP_MINUTES` overlap
- Cursor `last_activities_sync` advances only when `errors == 0`
- Full activity pull only when `full=True` (full reconcile)
- Regression tests with sanitized live-shaped fixture (no `DATE_MODIFY`)

## Stages (categories 1 & 39) after fix

From live `crm.status.list` (resolved semantics):

| pipeline | stage_id | name | semantics |
|----------|----------|------|-----------|
| 1 | C1:WON | Сделка успешна | success (`S`) |
| 1 | C1:LOSE | Сделка провалена | failure (`F`) |
| 1 | C1:APOLOGY | Предзакрытие (контроль РОП) | failure (`F`) |
| 39 | C39:WON | Переведен в работу | success (`S`) |
| 39 | C39:LOSE | Сделка провалена | failure (`F`) |

In-progress stages often have `SEMANTICS=null` in status dictionary; deal `STAGE_SEMANTIC_ID=P` fills `process` on upsert.

## Deal sample (limited smoke)

Page sizes were limited; no portal-wide deal walk.

| ID | pipeline | stage | manager | amount | closed |
|----|----------|-------|---------|--------|--------|
| 8475 | 1 | C1:EXECUTING | 13215 | 218520 | N |
| 8581 | 1 | C1:NEW | 21809 | 100400 | N |
| 8527 | 1 | C1:WON | 13040 | 122850 | Y |
| 7873 | 39 | C39:PREPAYMENT_INVOIC | 21149 | 120000 | N |

## Activities sample

- Count (sample deals only): 123
- OWNER_TYPE_ID=2 OK
- Fields seen include `LAST_UPDATED`; `DATE_MODIFY` not reliable
- No portal-wide activity list was executed for research or sync

## Database smoke import (original)

| Entity | After 1st | After 2nd |
|--------|----------:|----------:|
| managers | 72 | 72 |
| pipelines | 11 | 11 |
| stages | 141 | 141 |
| deals | 20 | 20 |
| activities | 123 | 123 |
| snapshots | 20 | 20 |
| change_events | 0 | 0 |

Idempotency: **PASS**

## API/UI (smoke dataset only)

**Not company-wide statistics.**

| Signal | After original smoke | After semantics fix (re-verify) |
|--------|---------------------:|-------------------------------:|
| won_count | 0 (blocked) | **1** |
| lost_count | 0 (blocked) | **2** |
| insufficient_stage_semantics | true | false / cleared |

## Manual verification — control values (REQUIRED)

Focus Analytics DB after limited re-import. Compare in Bitrix UI.

| ID | pipeline | stage | manager | amount | closed | future activity |
|---:|----------|-------|---------|--------|--------|-----------------|
| 8475 | 1 Сваи | C1:EXECUTING / Поставлен в график/монтаж (`process`) | Людмила Шифрина (13215) | 218520.00 | false | false (open overdue/past deadline) |
| 7873 | 39 Отложенный спрос | C39:PREPAYMENT_INVOIC / Ближайшее время (`process`) | Наташа Кучерова (21149) | 120000.00 | false | **true** (next 2026-10-10) |
| 8527 | 1 Сваи | C1:WON / Сделка успешна (`success`) | Данута Силивончик (13040) | 122850.00 | **true** | false |
| 8581 | 1 Сваи | C1:NEW / В работе/КП (`process`) | Анастасия Гузова (21809) | 100400.00 | false | **true** (next 2026-10-06 16:00 MSK) |

Bitrix URLs:

- https://focushouse.bitrix24.ru/crm/deal/details/8475/
- https://focushouse.bitrix24.ru/crm/deal/details/7873/
- https://focushouse.bitrix24.ru/crm/deal/details/8527/
- https://focushouse.bitrix24.ru/crm/deal/details/8581/

## Changes made (fix pass)

- `backend/app/integrations/bitrix/stage_semantics.py` — S/F/P mapping + `:WON`/`:LOSE` fallback
- `backend/app/integrations/bitrix/client.py` — allow `crm.status.list`
- `backend/app/services/sync_service.py` — status.list dictionaries; deal semantic enrich; activities `LAST_UPDATED`; category filter
- `backend/app/workers/sync_worker.py` — comment
- `backend/tests/test_stage_semantics.py`
- `backend/tests/test_missing_deals_and_activities_cursor.py`
- `backend/scripts/bitrix_semantics_activity_probe.py`, `bitrix_fix_verify.py`
- this report

## Tests

- pytest: **49 passed**
- frontend: not modified → lint/build not re-run

## Gates

| Gate | Result |
|------|--------|
| STAGE SEMANTICS | **PASS** |
| ACTIVITY INCREMENTAL | **PASS** |
| MANUAL VERIFICATION | **REQUIRED** |
| READY FOR FULL INITIAL SYNC | **NO** |

Worker remains stopped. Full sync must not start without explicit user confirmation.

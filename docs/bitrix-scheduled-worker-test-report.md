# Bitrix Scheduled Worker Test Report

## Status: **PASS**

Controlled local scheduled-worker test after successful full initial sync.  
Bitrix read-only. No VPS / prosrochka / SLA / Avito / AI / Telegram work.

## 1. Rebuild

| Item | Result |
|------|--------|
| `docker compose build --no-cache worker` | PASS |
| Image | `focus-analytics-worker` (fresh layers) |
| Bootstrap fix | `bootstrap_sync_mode full_reconcile=False` logged on start |

Worker no longer forces full reconcile on every start when `last_full_reconcile` is fresh.

## 2. Pre-start check

| Metric | Value |
|--------|------:|
| managers | 72 |
| pipelines | 2 |
| stages | 18 |
| deals | 1846 |
| activities | 16749 |
| snapshots | 1846 |
| change_events | 0 |
| missing_from_bitrix | 0 |

Cursors before start:

| Cursor | Value |
|--------|-------|
| last_deals_sync | 2026-10-06T11:24:37Z |
| last_activities_sync | 2026-10-06T11:42:25Z |
| last_full_reconcile | 2026-10-06T11:42:27Z |
| DEMO_MODE | **false** |
| Pre-start time (UTC) | 2026-10-06T11:47:30Z |

## 3. Start

- Started only `focus-analytics-worker-1` (recreated from new image)
- Interval: **5 minutes**
- Full initial sync **not** re-run (`full_reconcile=False` on bootstrap)

## 4. Three cycles

| Cycle | Started (UTC) | Finished (UTC) | Duration | Type | Deals items | Activities items | Errors |
|------:|---------------|----------------|---------:|------|------------:|-----------------:|-------:|
| 1 (bootstrap) | 11:50:16 | 11:50:25 | **~8.8s** | incremental `deals` | 83 | 156 | 0 |
| 2 (scheduled) | 11:55:16 | 11:55:25 | **~9.3s** | incremental `deals` | 77 | 147 | 0 |
| 3 (scheduled) | 12:00:16 | 12:00:39 | **~22.8s** | incremental `deals` | 78 | 145 | 0 |

Notes:

- All three used `cursor_info.full=false` (not full reconcile).
- `last_full_reconcile` stayed at **11:42:27Z** (not advanced every 5 minutes).
- Retries / HTTP 429 during worker test: none observed in worker logs.
- Cycle 3 dictionaries phase slower (~17.7s) due to Bitrix latency; deals/activities still ~2–3s each.

## 5. Incremental sync

| Check | Result |
|-------|--------|
| Not re-pulling all 1846 deals | PASS (77–83 / cycle) |
| Not re-pulling all 16749 activities | PASS (145–156 / cycle) |
| Deals filter DATE_MODIFY + overlap | PASS (`full=false`) |
| Activities filter LAST_UPDATED + overlap | PASS (`full=false`) |
| Full reconcile every 5 min | PASS (did **not** run) |

Compared to initial sync (~2477s / 41 min): incremental cycles are **~100–280× faster**.

## 6. Idempotency

| Check | Result |
|-------|--------|
| duplicate deal bitrix_id | **0** |
| duplicate activity bitrix_id | **0** |
| Overlap re-reads without false change storms | PASS |

Overlap re-fetches ~70–80 deals / ~150 activities per cycle, but unique rows remain stable except for real Bitrix changes (below).

## 7. Real change test

**OBSERVED** (natural Bitrix activity during the window; Bitrix was not modified for the test):

| Entity | Before | After | Δ | Explanation |
|--------|-------:|------:|--:|-------------|
| deals | 1846 | 1848 | +2 | New deals appeared in categories 1/39 |
| activities | 16749 | 16786 | +37 | New/updated activities in window |
| snapshots | 1846 | 1853 | +7 | New content hashes for changed/new deals |
| change_events | 0 | 3 | +3 | Real field changes: `title`, `stage_id`, `opportunity` (1 each) |

## 8. Cursors

| Cursor | Before | After | Forward? | Future jump? |
|--------|--------|-------|----------|--------------|
| last_deals_sync | 11:24:37Z | **12:00:36Z** | yes | no |
| last_activities_sync | 11:42:25Z | **12:00:39Z** | yes | no |
| last_full_reconcile | 11:42:27Z | 11:42:27Z | unchanged (correct) | n/a |

All cycles succeeded → cursors advanced. No failed cycle to test non-advance in this run (behavior covered by unit tests).

## 9. /system

| Field | Value |
|-------|-------|
| Database ready | ok |
| DEMO_MODE | false |
| Bitrix configured | true |
| Bitrix reachable | true |
| Data may be stale | false |
| Last successful sync | activities id=12 success, errors=0 @ 12:00:39Z |
| Last attempted sync | same (success) |
| Sync errors | 0 |
| Webhook in response | not present |

Backend container was recreated once so `/system` picked up current `.env` (worker already had webhook during the test).

## 10. Logs

| Check | Result |
|-------|--------|
| Traceback | none |
| scheduler RuntimeError | none |
| Unhandled exceptions | none |
| Webhook/token in logs | none (sanitized base only if logged) |
| Bitrix write methods | none |
| Restart loop | none |

## 11. Counts BEFORE / AFTER

| Entity | Before | After | Δ reason |
|--------|-------:|------:|----------|
| managers | 72 | 72 | unchanged |
| pipelines | 2 | 2 | unchanged |
| stages | 18 | 18 | unchanged |
| deals | 1846 | 1848 | +2 new deals from Bitrix |
| activities | 16749 | 16786 | +37 new/updated activities |
| snapshots | 1846 | 1853 | +7 new hashes for changed/new deals |
| change_events | 0 | 3 | real title/stage/opportunity changes |
| missing_from_bitrix | 0 | 0 | unchanged |

## 12. Performance

| Run | Duration |
|-----|---------:|
| Full initial sync | ~2477 s |
| Cycle 1 | ~9 s |
| Cycle 2 | ~9 s |
| Cycle 3 | ~23 s |

No bottleneck blocking continuous local sync. Dictionaries dominate when Bitrix is slow; still acceptable for 5-minute interval.

## 13. Tests

- pytest: **49 passed**
- frontend: not re-run (no FE changes)

## 14. Post-test

Worker **stopped** after 3 cycles (awaiting your decision for continuous local sync).  
No VPS/production deployment performed.

## Gates

- WORKER REBUILD: **PASS**
- CYCLE 1: **PASS**
- CYCLE 2: **PASS**
- CYCLE 3: **PASS**
- INCREMENTAL SYNC: **PASS**
- CURSORS: **PASS**
- IDEMPOTENCY: **PASS**
- DATABASE CONSISTENCY: **PASS**
- LOG SECURITY: **PASS**
- READY FOR CONTINUOUS LOCAL SYNC: **YES**

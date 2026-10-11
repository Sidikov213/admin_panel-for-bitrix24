# Manager Control V1 — Delivery Report

**Date:** 2026-10-07  
**Scope:** Workday Timeman + CRM activity only (no Time Control / idle / desktop)  
**Bitrix:** READ ONLY (`timeman.status` only; no open/close/pause/settings.set)

---

## What shipped

### Data collection
- Separate Timeman collector (`app/services/timeman_collector.py`)
- Runs after each CRM sync cycle (~5 min); failures never mark CRM sync failed
- Polls `timeman.status` for active managers with deals in synced categories (batch-capped)
- Tables: `manager_workday_snapshots`, `manager_workdays` (migration `20261007_0005`)
- Dedup by content hash; aggregates into per-day workdays
- `observed_at` = Focus poll time; Bitrix `TIME_START` / `TIME_FINISH` stored when present
- Local history starts at first successful collect (`timeman_history_since` in sync_state)

### UI
- Sidebar **Команда → Контроль менеджеров** → `/manager-control`
- Detail `/manager-control/[id]`: today workday + simple timeline + CRM metrics + week table
- Freshness: «Последнее обновление Timeman: HH:MM» with warning if >15 min
- Disabled hint: «Расширенный контроль активности» (Time Control not enabled)
- No productivity / efficiency / rating scores

### Status labels (objective only)
- Работает · Рабочий день завершён · Не начал рабочий день · Неизвестно

---

## Verification

| Check | Result |
|---|---|
| Alembic | `20261007_0005 (head)` applied |
| pytest | **80 passed** (`PYTHONPATH=/app`) |
| Frontend build | **PASS** (docker `next build`; routes include `/manager-control`) |
| Frontend lint | **PASS** (builder image; fixed pre-existing managers detail setState-in-effect) |
| Live worker | `timeman_collector_done managers=16 inserted=16 deduped=0 errors=0` |

---

## Final gates

```
TIMEMAN COLLECTOR: PASS
TODAY CONTROL: PASS
LOCAL HISTORY: PASS
CRM ACTIVITY: PASS
MANAGER DETAIL: PASS
WEEK VIEW: PASS
SYNC ISOLATION: PASS
TESTS: PASS
READY FOR MANAGER CONTROL V1: YES
```

---

## Out of scope (by design)

- Time Control idle / offline / desktop events
- Bitrix historical workday import (`record.list` unavailable)
- Productivity / efficiency scores
- Writing to Bitrix

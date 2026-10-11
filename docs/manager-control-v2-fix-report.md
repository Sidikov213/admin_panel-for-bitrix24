# Manager Control — post-diagnostic fix (V2)

**Date:** 2026-10-07 · **TZ:** Europe/Moscow  
**Constraints kept:** Bitrix READ ONLY · CRM sync unchanged · timezone unchanged · ASSIGNED_BY_ID / RESPONSIBLE_ID unchanged

---

## What changed

1. **Current Timeman state** from latest `manager_workday_snapshot` (`ORDER BY observed_at DESC`) — not `work_date == today`.
2. **Status normalization:** stale `EXPIRED` → `stale_unclosed` («Незакрытый рабочий день» + since label); never «Работает». Past `CLOSED` → `not_started` for today. Snapshot with unknown Bitrix status → «Неизвестный статус Bitrix», not empty/unknown-data.
3. **Today metrics** only when start/finish is today (or not_started); stale duration not copied into today.
4. **Monitored roster** (migration `20261007_0006`): auto from deals cat 1/39 + activity responsible + admin include/exclude; independent of Bitrix `is_active`.
5. **Board columns:** manager, Timeman status, start today, work time, breaks, CRM today, overdue, no next activity, last Timeman poll.
6. **History:** no synthetic past workdays from stale EXPIRED.

---

## BEFORE → AFTER (sample of 5)

| Manager | BEFORE | AFTER |
|---|---|---|
| **Юлия Замараева** | On board · «Неизвестно» · times «—» · CRM 0 | On board · **Незакрытый рабочий день** · с 29 мая 2026 · today times null · CRM 0 · poll 13:49 |
| **Алина Кашпур** | On board · «Неизвестно» · CRM 0 · overdue 2 | On board · **Незакрытый рабочий день** · с 17 января 2025 · today times null · CRM 0 · overdue 2 |
| **Мария Говор** | **Not on board** (`is_active=false`) · CRM SQL today rich | On board · bitrix_active=false · **Не начал рабочий день** · CRM **19** · overdue 32 · no_future 11 |
| **Анастасия Гузова** | **Not on board** | On board · **Не начал рабочий день** · CRM **15** · no_future 2 |
| **Андрей Тихон** | **Not on board** · CLOSED Mar 30 | On board · **Не начал рабочий день** (past CLOSED ≠ today completed) · CRM **34** · overdue 12 |

**Board:** 16 → **32** monitored · status mix AFTER: `not_started` 26 · `stale_unclosed` 6 · **0× «Неизвестно»** from missing today-join.

---

## Verification

| Check | Result |
|---|---|
| pytest | **91 passed** (`PYTHONPATH=/app`) |
| Frontend lint | **PASS** (Docker `node:20-alpine` / `eslint`) |
| Frontend build | **PASS** (`/manager-control` routes present) |
| Live board | 32 monitored · mix `not_started` 26 / `stale_unclosed` 6 |

---

## Gates

```
STALE TIMEMAN HANDLING: PASS
TODAY WORKDAY SEPARATION: PASS
ROSTER COMPLETE: PASS
CRM ACTIVE MANAGERS VISIBLE: PASS
UNKNOWN FALSE STATES REMOVED: PASS
TESTS: PASS
READY FOR MANAGER CONTROL: YES
```

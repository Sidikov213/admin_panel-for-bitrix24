# Manager Control V3 — Work Schedules, Violations & Reporting

**Date:** 2026-10-13  
**Branch:** `manager-control-v3` (from `cb3a062` — MC V2 + CI, without Avito probe)  
**Bitrix:** READ ONLY (no `timeman.open/close/pause`, no settings.write)

---

## What shipped

### Schedule engine
- Configurable `WorkSchedule` (name, TZ, weekdays, start/end, required minutes, grace/thresholds, breaks, enabled, is_default)
- **No company default norms hardcoded** — empty config → «Рабочий график не настроен», **no violations**
- Assignment priority: manager override → `department_key` → `is_default` → none

### Business calendar
- Local `CalendarDayOverride` (working / weekend / holiday / shortened / day_off)
- `ManagerAbsence` ranges (vacation / sick / absence / day_off)
- Non-working days do not create «не начал день»

### Violations (stateful)
Types: `WORKDAY_NOT_STARTED`, `LATE_START`, `WORKDAY_NOT_CLOSED`, `EARLY_FINISH`, `SHORT_WORKDAY`, `BREAK_LIMIT_EXCEEDED`, `STALE_UNCLOSED_DAY`  
**Not implemented (Time Control off):** IDLE / OFFLINE  

State: `OPEN` / `RESOLVED` · unique `(manager, work_date, type)` · severity INFO/WARNING/HIGH (configurable map)

### Enforcement / preview
- `ManagerControlPolicy.enforcement_start_date` — admin-set only (no auto November date)
- Before date: violations stored with `is_preview=true`
- Admin preview: «если применить график за доступные N дней» — only days with local Timeman history

### UI
- Board: status, start/end, worked, breaks, CRM, violations, last poll + filters
- Detail: schedule plan vs fact, violations, CRM
- Week / month per manager; team report + CSV
- Admin `/admin/manager-control`: schedules, assignments, calendar, policy, preview

### Worker isolation
After Timeman collect → `run_violation_evaluation_safe()` — never fails CRM sync or Timeman cycle.

### Honest limitations
Time Control disabled → no idle/offline/desktop presence.  
Work time = Timeman · CRM activity = separate metric.

---

## Migration

`20261013_0007_manager_control_v3` — schedules, assignments, calendar, absences, violations, policy.

---

## Tests

`tests/test_manager_control_v3.py` — assignment priority, no schedule, late/grace, not started/closed, early/short/breaks, holiday/absence/shortened, dedupe/resolve, enforcement preview, missing history, isolation, inactive+monitored.

---

## Gates

See chat final output.

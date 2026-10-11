# Manager Control — empty UI diagnostic (READ ONLY)

**Date:** 2026-10-07 · **TZ:** Europe/Moscow · day bounds UTC `2026-10-06T21:00` → `2026-10-07T20:59:59`  
**Board:** 16 managers · freshness ~13:16 · **no code/roster changes**

Board status mix: **9× «Не начал рабочий день»**, **7× «Неизвестно»**, CRM actions mostly **0**.

---

## Sample set

| # | Manager | id / bitrix | Why chosen |
|---|---|---|---|
| 1 | Юлия Замараева | 45 / 15679 | requested |
| 2 | Алина Кашпур | 2 / 11 | live Timeman EXPIRED + TIME_START (stuck day) |
| 3 | Мария Говор | 43 / 15673 | deals+activities today in SQL |
| 4 | Анастасия Гузова | 72 / 21809 | deals+activities today in SQL |
| 5 | Андрей Тихон | 1 / 1 | 34 completed activities today |

---

## Per-manager comparison

### 1) Юлия Замараева — ON BOARD

**Classification:** workday opened (stale EXPIRED) · CRM empty today

```
TIMEMAN RAW:
  STATUS=EXPIRED ACTIVE=true
  TIME_START=2026-05-29T10:26:52+03:00  TIME_FINISH=null
  DURATION=00:00:00  TIME_LEAKS=00:00:00  TZ_OFFSET=10800

DB SNAPSHOT:
  observed_at=2026-10-07 (collector ran)
  work_date=2026-05-29   ← from TIME_START, NOT today
  status_normalized=working
  same TIME_START / DURATION / TIME_LEAKS

DB WORKDAY TODAY: null

API /manager-control:
  status_label=Неизвестно  workday_available=false
  time_start/duration/leaks=null  crm_actions_today=0

CRM SQL FACT (today):
  created=0 modified=0 completed_acts=0 stage=0 opp=0 overdue=0 no_future=0

UI VALUE:
  Статус «Неизвестно», начало/время/перерывы «—», CRM 0
```

**Root:** snapshot exists, but API joins only `work_date == today` → miss → unknown + dashes.

---

### 2) Алина Кашпур — ON BOARD (Bitrix «работал» = stale open day)

**Classification:** workday opened (stale EXPIRED since 2025-01-17)

```
TIMEMAN RAW:
  STATUS=EXPIRED TIME_START=2025-01-17T10:13:08+03:00
  DURATION=00:00:00 TIME_LEAKS=00:00:00

DB SNAPSHOT: work_date=2025-01-17 status=working (collected today)
DB WORKDAY TODAY: null

API: Неизвестно / — / crm_actions=0  overdue=2

CRM SQL: created=0 completed_acts=0 (overdue=2)
```

Same join bug. Bitrix is **not** returning a fresh today start — abandoned EXPIRED day.

---

### 3) Мария Говор — NOT ON BOARD

**Classification:** workday not started · CRM rich today

```
TIMEMAN RAW: { "STATUS": "CLOSED" }  (no TIME_*)
PARSED: not_started / «Не начал рабочий день» / work_date=today

DB SNAPSHOT: []   (not polled — is_active=false → excluded from collector roster)
DB WORKDAY TODAY: null
IN_BOARD: false

CRM SQL FACT (today):
  created=1  modified=9  completed_acts=7
  stage_changes=17  opportunity_changes=1
  overdue=32  no_future=11

UI: not visible on /manager-control
```

---

### 4) Анастасия Гузова — NOT ON BOARD

```
TIMEMAN RAW: STATUS=CLOSED only → not_started
DB: no snapshot (inactive)
CRM SQL today: created=1 modified=6 completed=7 stage=9 opp=1 no_future=2
UI: not on board
```

---

### 5) Андрей Тихон — NOT ON BOARD

```
TIMEMAN RAW: CLOSED with TIME_START/FINISH=2026-03-30 (old closed day)
PARSED work_date=2026-03-30 → would not attach to today anyway
CRM SQL today: completed_acts=34 overdue=12 no_future=7 created=0
is_active=false → not on board / not collected
```

---

## Board-wide facts

1. **Top CRM activity today (completed activities)** — all `is_active=false`, **none on board**:
   - Тихон 34, Шаплова 9, Гузова 7, Говор 7, Кучерова 7, …
2. **On-board CRM** for sampled active managers: mostly **0** — SQL confirms, not an aggregation miss for those IDs.
3. **«Неизвестно»** rows all have snapshots with `work_date` in the past (EXPIRED/CLOSED stale) and **no** `manager_workdays` row for 2026-10-07.
4. **«Не начал…»** rows correctly map `STATUS=CLOSED` without TIME_START; times are null → UI shows «—» for start/duration (status text is OK).

---

## Timezone

| Check | Result |
|---|---|
| APP_TIMEZONE | Europe/Moscow |
| Today bounds | UTC −03:00 midnight Moscow → correct |
| Bitrix `+03:00` parse | OK (stored as UTC) |
| Deal create `2026-10-06T23:13:22Z` counted as today | YES (02:13 Moscow) |

**TIMEZONE BUG: NO** (day window is correct). Empty CRM on board is not a TZ off-by-one.

---

## Mapping

| Metric | Key used | Correct? |
|---|---|---|
| Deals created/modified / stage / opp / no_future / overdue owner | `CrmDeal.assigned_by_id` → manager.id | YES |
| Completed activities | `CrmActivity.responsible_id` → manager.bitrix_id | YES |

**MAPPING BUG (identity):** NO for ASSIGNED vs RESPONSIBLE.  
**LOGIC BUG:** YES — today board ignores latest Timeman snapshot when `work_date ≠ today`; EXPIRED stale sessions look like «no data».  
**ROSTER FILTER:** `is_active=True` hides managers who actually have CRM today (diagnostic only; roster not changed).

---

## Why UI looks empty

| Symptom | Exact cause |
|---|---|
| Статус «Неизвестно» + «—» | Collector saved snapshot under old `work_date` from Bitrix TIME_START; list API only reads today → treats as missing |
| Начало/длительность «—» при «Не начал» | Bitrix `{STATUS:CLOSED}` without TIME_* — fields truly null; status label is present |
| CRM 0 on board | Active roster has little/no CRM today; real CRM movers are `is_active=false` and filtered out |
| Nobody «Работает» with today's start | Live Bitrix EXPIRED days are months/years old; true CLOSED-without-start for many |

---

## Gates

```
TIMEMAN EMPTY REASON: API binds workday to calendar today only; Bitrix EXPIRED returns stale TIME_START → snapshot stored on old work_date → today row missing → UI «Неизвестно»/«—» despite collected data. Also many real CLOSED={STATUS only} → times null (expected).

CRM ZERO REASON: On-board active managers largely have 0 CRM events today (SQL-confirmed). Managers with real CRM today are is_active=false and excluded from board/collector (e.g. Говор, Гузова, Тихон).

TIMEZONE BUG: NO
MAPPING BUG: YES (today vs observation/status join; not ASSIGNED/RESPONSIBLE)
DATA REALLY EMPTY: PARTIAL — Timeman stale/not-started is real Bitrix state; CRM empty for board roster is mostly real; CRM non-empty for inactive users filtered out
FIX REQUIRED: YES
```

### Fix directions (not implemented)

1. For board «today»: use **latest snapshot by observed_at**, or map EXPIRED/OPENED to **observation date** when TIME_START is not today; never show «Неизвестно» if a snapshot exists for that manager after collect.  
2. Distinguish stale EXPIRED (start date ≪ today) in status copy.  
3. Separately (roster policy): whether `is_active=false` managers with CRM today should appear — out of scope per request.

---

Stopped after diagnosis. No roster / Manager Control code changes.

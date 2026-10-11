# Manager Control — Bitrix Timeman LIVE Probe (re-run)

**Date:** 2026-10-07 (second run after webhook reissue)  
**Portal:** `focushouse.bitrix24.ru` (sanitized)  
**Mode:** Strict READ ONLY · no `timeman.open/close/pause` · no `*.settings.set` · no portal setting changes  
**Raw:** `docs/manager-control-bitrix-probe-raw.json`  
**Webhook secret:** never printed  

Host `.env` / `backend/.env` updated to the new incoming webhook. Backend + worker recreated so CRM sync uses the new token (CRM scopes unchanged + `timeman` added).

---

## A / B / C / D distinction

### A. Scope exists — **YES**

| Check | Result |
|---|---|
| `scope` / `app.info` | `crm`, `timeman`, `user_brief` |
| Timeman methods in `methods` list | **14** |

### B. Timeman module enabled — **YES**

| Check | Result |
|---|---|
| `timeman.status` (self + 3 managers) | **200 OK**, workday payloads |
| `TIMEMAN_TOOL_DISABLED` | not returned |

Webhook owner self-status sample: `{ "STATUS": "CLOSED" }` (minimal fields when day closed / no open day).  
Managers with open/expired days return full keys including `TIME_START`, `DURATION`, `TIME_LEAKS`, etc.

### C. Time Control enabled — **NO**

| Check | Result |
|---|---|
| `timeman.timecontrol.settings.get` | **200 OK** |
| `active` | **`false`** |
| `register_idle` / `register_offline` / `register_desktop` | `true` in config, but module inactive |
| `timeman.timecontrol.reports.get` | callable, **`days_count: 0`** for sampled users |

So Time Control API is reachable, but the tool is **not active** on the portal → no idle/offline/desktop event stream.

### D. Concrete field availability

| Field | Live result | Evidence |
|---|---|---|
| Workday `STATUS` | **AVAILABLE** | Managers: `EXPIRED` / self: `CLOSED` |
| `TIME_START` / `TIME_FINISH` | **AVAILABLE** | Present on manager status when day started (`TIME_START_present: true`; finish null while open/expired) |
| `DURATION` | **AVAILABLE** | Returned (`00:00:00` while unfinished/`EXPIRED`) |
| `TIME_LEAKS` (breaks) | **AVAILABLE** | Returned on manager status |
| Last activity | **NOT AVAILABLE** | No dedicated field; TC reports empty |
| IDLE | **NOT AVAILABLE** | TC `active=false`, no IDLE events |
| OFFLINE | **NOT AVAILABLE** | same |
| DESKTOP_* | **NOT AVAILABLE** | same |

---

## Limited sample (3 managers)

Names masked. No PII beyond bitrix user ids needed for technical check.

| user_id | Status | TIME_START | DURATION | TIME_LEAKS | TC days |
|---|---|---|---|---|---|
| 11 | EXPIRED | yes | yes | yes | 0 |
| 13 | EXPIRED | yes | yes | yes | 0 |
| 23 | (see raw) | yes/varies | yes | yes | 0 |

All three: `timeman.status` OK · `timecontrol.reports.get` OK with empty `days`.

---

## History

| Window | Result | Notes |
|---|---|---|
| Today | **AVAILABLE** | Via `timeman.status` current workday |
| Yesterday | **NOT AVAILABLE** | `timeman.record.list` → `ERROR_METHOD_NOT_FOUND` (classic + REST 3.0 probe paths) |
| Last 7 days | **NOT AVAILABLE** | Same — no historical record list API working on this webhook/portal path |

`timeman.settings.get` also returns `ERROR_METHOD_NOT_FOUND` (not required for status).

No bulk historical import was run.

---

## TIMEMAN vs TIME CONTROL

| Domain | Status |
|---|---|
| **TIMEMAN** — start/end of workday, status, duration, breaks | **Working** via `timeman.status` |
| **TIME CONTROL** — idle / offline / desktop events | **Off** (`active=false`); reports empty |

---

## CRM ACTIVITY (Focus DB)

Still **AVAILABLE** and separate from work time (deals/activities/change events). Unchanged approach from previous probe.

---

## Security / config (nothing auto-changed)

| Topic | Finding |
|---|---|
| Webhook scopes now | `crm` + `user_brief` + **`timeman`** |
| Extra Bitrix config for MVP workday board | **Not required** |
| For idle/offline/desktop | Enable Time Control on portal (`active=true`) — **manual**; desktop app needed for idle/desktop registration |
| Write / settings APIs | Not called |

---

## Target build readiness (no UI written)

**Can build now (PARTIAL):**

- `/manager-control` — today: status, start, duration, breaks + CRM activity columns  
- Detail page: current workday from `timeman.status` + CRM day/week stats  

**Cannot build yet without portal change:**

- Idle / offline / desktop timeline  
- Reliable multi-day Timeman history (`record.list` not available)

---

```
TIMEMAN SCOPE: YES
TIMEMAN ENABLED: YES
TIME CONTROL ENABLED: NO

WORKDAY STATUS: AVAILABLE
START/FINISH: AVAILABLE
DURATION: AVAILABLE
BREAKS: AVAILABLE

LAST ACTIVITY: NOT AVAILABLE
IDLE: NOT AVAILABLE
OFFLINE: NOT AVAILABLE
DESKTOP EVENTS: NOT AVAILABLE

TODAY HISTORY: AVAILABLE
YESTERDAY HISTORY: NOT AVAILABLE
7 DAY HISTORY: NOT AVAILABLE

CRM ACTIVITY METRICS: AVAILABLE

NEEDS BITRIX CONFIG CHANGE: NO
NEEDS DESKTOP APP: YES

READY TO BUILD MANAGER CONTROL: PARTIAL
```

**Gate notes**

- `NEEDS BITRIX CONFIG CHANGE: NO` — for workday + CRM MVP. Enabling Time Control is optional and only needed for idle/offline/desktop.  
- `NEEDS DESKTOP APP: YES` — settings already intend to register desktop/idle/offline; without desktop clients those signals will not appear even after TC is activated.  
- `READY … PARTIAL` — workday Timeman + CRM yes; presence telemetry + multi-day Timeman history no.

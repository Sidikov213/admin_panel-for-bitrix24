# Focus Analytics — Stage 2 Analytics Report

**Branch:** `stage2-analytics`  
**Base (stable Bitrix foundation):** commit `1f91d36` / tag `bitrix-integration-stable-v1`  
**Date:** 2026-10-07  
**Dataset at verification:** 1853 deals / 16894 activities  
**Worker:** left running continuously (image unchanged; no long stop)

## Summary

Stage 2 builds **executive sales analytics** on top of the verified Bitrix READ ONLY sync. Sync architecture, cursors, and worker loop were not rewritten. New work is aggregate SQL, period comparison, attention facts, targets plan/fact, reports, stalled-rules schema (disabled by default), and UI for managers/dashboard/pipelines/overdue/stalled/reports/system/deal details.

Out of scope (unchanged / not connected): AI, Avito, call transcription, Telegram reports, production VPS, Bitrix writes, webhook UI.

---

## What was implemented

### 1. Dashboard (`/dashboard`)
- Period picker: today, yesterday, 7 days, current/previous week, current/previous month, custom range
- KPI + programmatic comparison vs previous period (absolute + %, no ∞% when previous = 0)
- Block **«Требуют внимания»** with objective facts only
- Plan / Fact / % / remaining (fact = sum WON opportunity in period; «План не задан» if no target)
- Data freshness banner (stale > 15 min / sync failed)

### 2. Attention / money requiring attention
- Categories: no future activity, overdue activity, idle observation, overdue next contact fact, lost after idle observation, money at risk
- **«Сумма сделок, требующих внимания»**: active deals with no future activity **OR** open overdue activity; each deal counted once

### 3. Stalled rules engine
- Migration `20261007_0003` → table `stalled_rules`
- Fields: pipeline, stage, max_idle_minutes, future_activity_required, max_next_activity_minutes, deal_status, use_business_calendar, enabled, name, note
- **No default SLA thresholds**; rules default `enabled=false`
- Admin UI: `/settings/rules` + API `/api/v1/stalled-rules`
- Until rules enabled: UI shows objective facts only

### 4. Managers (`/managers`, `/managers/[id]`)
- Per-manager aggregates: active/new/won/lost, amounts, overdue, no-future share, stage changes
- Period switch + comparison
- Drill-down: metric → deal list (`/managers/{id}/deals?...`)
- No “efficiency ranking”

### 5. Deals (`/deals/[id]`)
- Title, pipeline, stage, manager, amount, created/modified/closed
- Activities (current / overdue / future), last observed activity & stage change
- Snapshots + change events timeline
- `observed_at` treated as poll discovery time, not Bitrix event time
- Direct Bitrix portal links when `BITRIX_PORTAL_URL` set

### 6. Pipelines (`/pipelines`)
- Funnel for Сваи / Отложенный спрос (and other synced pipelines)
- Current distribution (count, sum, share of active) vs period won/lost/stage moves
- Explicit distinction: **current distribution** ≠ **historical conversion** (no fake conversion history)

### 7. Overdue (`/overdue`)
- 1 Bitrix activity = 1 overdue row
- Columns: manager, deal, activity, deadline, overdue duration, pipeline, stage, amount
- Filters + group by manager / pipeline

### 8. No future (`/stalled?mode=no_future`)
- Active deals without future planned activity
- Summary count + sum of real opportunity
- Bitrix links

### 9. Reports (`/reports`)
- Weekly-style report: overview, problems, managers table, vs previous week
- No AI narrative

### 10. Targets
- Company / manager monthly targets (existing CRUD extended for plan/fact)
- Dashboard plan/fact wiring

### 11. System (`/system`)
- Worker status (inferred from sync freshness), Bitrix reachability, DB, last successful/attempted sync, cursors, last full reconcile, duration, errors/retries 24h, totals (deals/activities/snapshots/events)
- **Webhook details not exposed**

### 12. Design
- Light minimal executive SaaS layout, large KPIs, period controls, freshness, quieter tables/charts

---

## Endpoints (API `/api/v1`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/dashboard` | KPIs, comparison, attention, plan/fact, freshness |
| GET | `/managers` | Manager aggregates + period |
| GET | `/managers/{id}` | Manager detail KPIs |
| GET | `/managers/{id}/deals` | Drill-down deal list |
| GET | `/deals`, `/deals/{id}` | List + analytic detail |
| GET | `/pipelines?analytics=true\|false` | Funnel analytics or dictionary list |
| GET | `/overdue` | Overdue activities |
| GET | `/stalled` | No-future / stalled modes |
| GET/POST/PATCH/DELETE | `/stalled-rules` | Configurable rules (admin) |
| GET | `/reports` | Period executive report |
| GET | `/system` | Ops status (no webhook) |
| CRUD | `/targets` | Sales targets |

Period query params (where applicable): `preset`, `period_start`, `period_end`.

---

## Pages checked

| Page | Route | Build | HTTP (unauth) |
|------|-------|-------|----------------|
| Dashboard | `/dashboard` | yes | 307 → login |
| Managers | `/managers`, `/managers/[id]` | yes | 307 |
| Deals | `/deals`, `/deals/[id]` | yes | 307 |
| Pipelines | `/pipelines` | yes | 307 |
| Overdue | `/overdue` | yes | 307 |
| No future | `/stalled` | yes | 307 |
| Reports | `/reports` | yes | 307 |
| System | `/system` | yes | 307 |
| Rules admin | `/settings/rules` | yes | 307 |
| Login | `/login` | yes | 200 |

Frontend production image rebuild: **OK** (`next build` + TypeScript green).

---

## DB migrations

| Revision | Change |
|----------|--------|
| `20261007_0003` | `stalled_rules` table + indexes (`pipeline_bitrix_id`, `enabled`) |

Applied against local Postgres (host `55432`). No changes to Bitrix sync tables/cursors.

---

## KPI formulas (high level)

| Metric | Formula |
|--------|---------|
| Active deals | `closed=false`, not missing from Bitrix |
| Active amount | `SUM(opportunity)` on active |
| New deals | `DATE_CREATE` in period (Europe/Moscow day bounds) |
| Won / lost | Closed + stage semantics success/failure + `CLOSEDATE` in period |
| Won amount | `SUM(opportunity)` on won in period |
| Overdue activities | Unique activities: `deadline < now` AND `completed=false` |
| No future | Active + `has_future_activity=false` |
| Money requiring attention | Active AND (no future OR has open overdue activity), **deduped** |
| Plan fact | Sum WON opportunity in period vs `sales_targets` |
| Comparison | `abs_delta`, `pct_delta`; `pct_delta=null` if previous = 0 |

---

## Performance (local Docker, ~1853 deals / ~17k activities)

Service-layer timings inside backend container:

| Call | Time |
|------|------|
| Dashboard (current week + comparison + attention + plan/fact) | **985 ms** |
| Pipeline analytics | 370 ms |
| Weekly report | 379 ms |
| Attention items | 125 ms |
| Money requiring attention | 6 ms |
| No-future summary | 4 ms |

Target «ordinary API &lt; 1s locally»: **met** for dashboard (under 1s) and comfortably met for the rest. Aggregates use SQL `COUNT`/`SUM`/subqueries rather than N+1 ORM loops for primary KPIs.

---

## Tests

```
pytest  →  59 passed
```

New / Stage-2-focused coverage includes:
- `tests/test_period_comparison.py` — deltas, presets, previous-period pairing, zero-base %
- `tests/test_attention_and_targets.py` — money dedupe, no_future, plan/fact
- `tests/test_stalled_rules_disabled.py` — rules off by default / facts-only path

Frontend: **`next build` PASS** (includes TypeScript). ESLint binary is not present in the standalone runtime image; lint was not re-run locally (no host `node_modules`). Typecheck gate via Docker build is green.

---

## Bitrix foundation integrity

| Check | Status |
|-------|--------|
| Worker continuous | RUNNING (not rebuilt / not stopped for Stage 2) |
| Bitrix mode | READ ONLY |
| Sync architecture | Unchanged |
| DEMO_MODE | false |
| Data present | deals≈1853, activities≈16894 |

---

## Remaining limitations

- Stalled **business SLA rules** are schema-ready but empty/disabled until sales regulations are approved
- Historical conversion rates are intentionally limited to observed change events; long history may still be thin
- Manager “effectiveness rating” intentionally absent
- Worker status on `/system` is inferred from sync freshness (no separate process probe)
- AI / Avito / calls / Telegram / VPS deferred to later stages
- Dashboard cold path can approach ~1s on full comparison; further index tuning possible later

---

## Checklist

```
DASHBOARD: PASS
MANAGERS: PASS
DEALS: PASS
OVERDUE: PASS
NO_FUTURE: PASS
PIPELINES: PASS
REPORTS: PASS
TARGETS: PASS
TESTS: PASS
READY FOR SALES RULES: YES
```

**READY FOR SALES RULES: YES** — configurable `stalled_rules` + admin UI exist; no invented thresholds are active. After the department approves SLA values, enable rules without rewriting the analytics foundation.

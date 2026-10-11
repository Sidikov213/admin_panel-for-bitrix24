# Focus Analytics — Stage 2.5 Sales Rules Engine

**Branch:** `stage25-sales-rules`  
**Base:** Stage 2 analytics (`stage2-analytics`) on Bitrix foundation `bitrix-integration-stable-v1`  
**Date:** 2026-10-07  

## Summary

Configurable Sales Rules Engine on top of Stage 2 analytics. Bitrix remains READ ONLY. Sync architecture unchanged. Evaluation runs **after** a successful sync cycle and cannot fail the sync. Default rules are empty/disabled — no invented SLA values. Objective signals (overdue, no_future, observed idle) continue independently.

---

## DB schema

| Table | Purpose |
|-------|---------|
| `sales_rules` | Rule config: pipeline/stage scope, thresholds, severity, required_fields, comment fields (capability flag) |
| `sales_rule_violations` | OPEN/RESOLVED occurrences with type, severity, details, threshold, detected_at, resolved_at |
| `sales_rule_audits` | Who/when/before/after for create/update/delete/enable/disable (no secrets) |
| `bitrix_deal_fields` | READ ONLY metadata from `crm.deal.fields` for required_fields picker |

**Migration:** `20261007_0004` (revises `20261007_0003`)

**Partial unique index (Postgres):** one OPEN row per `(deal_id, rule_id, violation_type)`.

### Violation state model

1. At most one **OPEN** violation per deal + rule + type.
2. Condition clears → `status=resolved`, `resolved_at` set.
3. Condition returns → **new OPEN occurrence** (history preserved for “new during period”).
4. Sync cycles never create duplicate OPEN rows for the same key.

---

## Evaluation architecture

```
Bitrix sync cycle (dictionaries → deals → activities)
        ↓ success only
sales_rules evaluation (own DB session, try/except)
        ↓ never writes to Bitrix
OPEN/RESOLVED violations updated
```

- Hook: `sync_worker._run_sales_rules_evaluation_after_sync` after successful `run_sync_cycle`
- Manual job: `POST /api/v1/sales-rules/evaluate` (admin)
- Evaluation failure is logged; sync success/watermark unaffected
- Batch load: active deals + overdue owner set + latest snapshots; no N+1 per deal for rules

**Priority:** stage-specific rule overrides pipeline/global for the same check attribute.

---

## Supported rule types

| Type | Trigger |
|------|---------|
| `NO_FUTURE_ACTIVITY` | `future_activity_required=true` and no future activity |
| `OVERDUE_ACTIVITY` | `overdue_activity_allowed=false` and open overdue activity |
| `IDLE_TOO_LONG` | idle minutes (observed activity/modify) > `max_idle_minutes` |
| `STAGE_TOO_LONG` | stage duration (observed stage change) > `max_stage_duration_minutes` |
| `NEXT_ACTIVITY_TOO_FAR` | next deadline ahead > `max_next_activity_minutes` |
| `REQUIRED_FIELD_MISSING` | fields from mapping / latest snapshot payload empty |

## Unsupported / disabled capabilities

| Type | Status |
|------|--------|
| `COMMENT_MISSING` / `COMMENT_TOO_OLD` | **Unsupported** — no Bitrix timeline/comments READ ONLY sync today. Fields stored; evaluation no-ops; UI documents limitation. |
| Invented default SLA | **Not shipped** — rules default `enabled=false`, empty thresholds |

---

## Endpoints

| Method | Path | Notes |
|--------|------|-------|
| GET/POST | `/api/v1/sales-rules` | List / create |
| GET/PATCH/DELETE | `/api/v1/sales-rules/{id}` | CRUD |
| POST | `/api/v1/sales-rules/preview` | Impact preview (no persist) |
| POST | `/api/v1/sales-rules/evaluate` | Manual evaluation |
| GET | `/api/v1/sales-rules/violations` | List violations |
| GET | `/api/v1/sales-rules/audits` | Audit trail (admin) |
| GET | `/api/v1/sales-rules/deal-fields` | Field picker catalog |
| POST | `/api/v1/sales-rules/deal-fields/sync` | Sync `crm.deal.fields` |

Also wired into: `/dashboard` (`rule_violations` + attention split), `/managers`, `/deals/{id}` (`violations`), `/reports` (`regulation_violations`).

---

## UI pages

| Page | Route |
|------|-------|
| Admin sales rules | `/admin/sales-rules` — list, create/edit, enable, preview, field sync, manual evaluate |
| Dashboard | Objective signals vs business violations; rule KPIs |
| Deal detail | Active + resolved violations |
| Managers | open / high / resolved / violation_rate |
| Reports | «Нарушения регламента» or «Регламент не настроен» |

---

## Performance

Target: full evaluation &lt; 2s locally on ~2k deals; API pages &lt; 1s.

Measured on live dataset (~1853 deals): evaluation with **0 enabled rules** ≈ **230 ms**. With enabled rules, cost is O(deals × matching rules) after batch preloads (overdue owners, latest snapshots).

---

## Tests

```
pytest → 69 passed
```

Coverage in `tests/test_sales_rules_engine.py`:
- rule priority (stage > pipeline)
- disabled rules
- no_future / overdue / idle / stage duration / required fields
- preview non-persistence
- duplicate prevention + resolve + reopen occurrence
- severity aggregates / dashboard / manager stats
- timezone preset + human description / comment capability note

Frontend: `next build` + TypeScript green (Docker). Host eslint not available without `node_modules` (same as Stage 2).

---

## Limitations

1. Comment rules cannot evaluate until timeline/comment READ ONLY sync is designed.
2. Required UF fields depend on latest `DealSnapshot.payload` (only when deal content hash changes) — empty snapshot may miss UF values until next change.
3. Worker must run Stage 2.5 image for post-sync evaluation; backend serves APIs independently.
4. No performance score / manager ranking.
5. Business calendar not implemented (`use_business_calendar` left to later regulation).

---

## Checklist

```
RULE ENGINE: PASS
ADMIN UI: PASS
PREVIEW: PASS
VIOLATIONS: PASS
DEAL INTEGRATION: PASS
MANAGER ANALYTICS: PASS
REPORTS: PASS
TESTS: PASS
READY FOR REAL SALES REGULATION: YES
```

Admin can create enabled rules with real thresholds after department approval. No default SLA values are preloaded.

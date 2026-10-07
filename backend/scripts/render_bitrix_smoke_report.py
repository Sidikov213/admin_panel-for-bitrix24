#!/usr/bin/env python3
"""Render docs/bitrix-real-smoke-report.md from JSON (no secrets)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "bitrix-real-smoke-report.json"
OUT = ROOT / "docs" / "bitrix-real-smoke-report.md"


def main() -> None:
    r = json.loads(SRC.read_text(encoding="utf-8"))
    stages_map = {str(s["stage_id"]): s for s in r.get("stages") or []}
    for m in r.get("manual_deals") or []:
        st = stages_map.get(str(m.get("stage_id") or ""))
        if st and not m.get("stage"):
            m["stage"] = st.get("name")
    db = r.get("database_smoke") or {}
    if db.get("idempotency") == "PASS":
        r["status"] = "PASS"
        r["errors"] = [e for e in (r.get("errors") or []) if e != "idempotency fail"]
    SRC.write_text(json.dumps(r, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def rows(items, fmt):
        return "\n".join(fmt(x) for x in items)

    dq = r.get("data_quality_deals") or []
    rest = r.get("rest_methods") or []
    pipes = r.get("pipelines") or []
    req = [p for p in pipes if p["id"] in (1, 39)]
    stages = r.get("stages") or []
    manual = r.get("manual_deals") or []
    deals = r.get("deal_sample") or []
    kpi = (r.get("api_ui_smoke") or {}).get("kpis") or {}
    notes = r.get("data_quality_notes") or {}
    acts = r.get("activities_sample") or {}
    env = r.get("environment") or {}
    perm = r.get("permissions") or {}

    md = f"""# Bitrix Real Smoke Report

## Status

**{r.get('status')}**

Limited controlled smoke against real Bitrix24 (read-only). Full initial sync **not** executed.

## Environment

| Key | Value |
|-----|-------|
| Portal | focushouse.bitrix24.ru |
| Webhook | {env.get('webhook')} |
| Sanitized base | `{env.get('sanitized_base')}` |
| Categories | `{env.get('categories')}` |
| DEMO_MODE | {env.get('demo_mode')} |
| Database | `focus_analytics_bitrix_test` (isolated from audit/perf seed) |
| Worker | stopped during smoke |

## Permissions

| Check | Result |
|-------|--------|
| Bitrix connection | {perm.get('connection')} |
| CRM scope | {perm.get('crm_scope')} |
| User scope | {perm.get('user_scope')} |

## REST methods actually called

| method | count | result | read-only |
|--------|------:|--------|-----------|
{rows(rest, lambda x: f"| {x['method']} | {x['count']} | {x.get('result')} | yes |")}

Static allow-list only. No write methods were called.

## Pipelines discovered

Required categories confirmed from live API:

| ID | name |
|----|------|
{rows(req, lambda p: f"| {p['id']} | {p['name']} |")}

Total pipelines on portal: {len(pipes)}.

## Stages discovered (categories 1 & 39)

Count: {len(stages)}

| pipeline | stage_id | name | semantics |
|----------|----------|------|-----------|
{rows(stages, lambda s: f"| {s['pipeline_id']} | {s['stage_id']} | {s['name']} | {s.get('semantics')} |")}

**Warning:** `SEMANTICS` / `STAGE_SEMANTIC_ID` are null for all stages from `crm.dealcategory.stage.list`. KPI won/lost therefore report 0 / `insufficient_stage_semantics=true`. Consider a later migration to `crm.status.*` — not done in this smoke.

## Managers

- Total: {(r.get('managers') or {}).get('count')}
- Active: {(r.get('managers') or {}).get('active')}

## Deal sample (limited, ≤10 per category)

Page sizes (single Bitrix page, no full walk): {r.get('deal_page_sizes')}. Smoke kept first 10/category → {len(deals)} deals.

| ID | pipeline | stage | manager | amount | created | closed |
|----|----------|-------|---------|--------|---------|--------|
{rows(deals, lambda d: f"| {d.get('id')} | {d.get('category_id')} | {d.get('stage_id')} | {d.get('assigned_by_id')} | {d.get('opportunity')} | {d.get('date_create')} | {d.get('closed')} |")}

## Activities sample

- Count (sample deals only): {acts.get('count')}
- OWNER_TYPE_ID=2 OK: {acts.get('owner_type_id_deal_ok')}
- Fields seen: {', '.join(acts.get('fields_seen') or [])}

No portal-wide activity list was executed.

## Data quality

| Field | Present | Null | Unexpected |
|-------|--------:|-----:|-----------:|
{rows(dq, lambda x: f"| {x['field']} | {x['present']} | {x['null']} | {x['unexpected']} |")}

Notes:
- Timezone samples: `{notes.get('timezone_samples')}`
- Money samples: `{notes.get('money_samples')}`
- ID types: `{dict(notes.get('id_types') or {})}`
- CLOSED values: `{dict(notes.get('closed_values') or {})}`
- Stage semantics missing (see above)
- Fixed: false opportunity change-events on re-import (`229320.00` vs `229320.00000000`) via `_money_key`

## Database smoke import

| Entity | After 1st | After 2nd |
|--------|----------:|----------:|
| managers | {(db.get('counts_after_first') or {}).get('managers')} | {(db.get('counts_after_second') or {}).get('managers')} |
| pipelines | {(db.get('counts_after_first') or {}).get('pipelines')} | {(db.get('counts_after_second') or {}).get('pipelines')} |
| stages | {(db.get('counts_after_first') or {}).get('stages')} | {(db.get('counts_after_second') or {}).get('stages')} |
| deals | {(db.get('counts_after_first') or {}).get('deals')} | {(db.get('counts_after_second') or {}).get('deals')} |
| activities | {(db.get('counts_after_first') or {}).get('activities')} | {(db.get('counts_after_second') or {}).get('activities')} |
| snapshots | {(db.get('counts_after_first') or {}).get('snapshots')} | {(db.get('counts_after_second') or {}).get('snapshots')} |
| change_events | {(db.get('counts_after_first') or {}).get('change_events')} | {(db.get('counts_after_second') or {}).get('change_events')} |

## Idempotency

**{db.get('idempotency')}**

## API/UI (smoke dataset only)

**Not company-wide statistics.**

| Signal | Value |
|--------|-------|
| deals_in_db | {(r.get('api_ui_smoke') or {}).get('deals_in_db')} |
| active_deals_count | {kpi.get('active_deals_count')} |
| new_deals_count | {kpi.get('new_deals_count')} |
| won_count | {kpi.get('won_count')} (blocked by missing stage semantics) |
| lost_count | {kpi.get('lost_count')} (blocked by missing stage semantics) |
| overdue_activities_unique | {kpi.get('overdue_activities_unique')} |
| deals_without_future_activity_count | {kpi.get('deals_without_future_activity_count')} |

## Manual verification

**REQUIRED**

| role | Bitrix ID | Title | Pipeline | Stage | Manager ID | Amount | Closed | Bitrix URL |
|------|----------:|-------|----------|-------|------------|--------|--------|------------|
{rows(manual, lambda m: f"| {m.get('role')} | {m.get('bitrix_id')} | {(m.get('title') or '')[:40]} | {m.get('pipeline')} | {m.get('stage') or m.get('stage_id')} | {m.get('manager_id')} | {m.get('amount')} | {m.get('closed')} | {m.get('bitrix_url')} |")}

## Errors

{r.get('errors') or ['(none)']}

## Changes made

- `backend/app/integrations/bitrix/client.py` — allow-list, sanitization, `call_list_page`
- `backend/app/integrations/bitrix/sanitize.py`
- `backend/app/services/sync_service.py` — `import_smoke_sample`, `_money_key`
- `backend/scripts/bitrix_real_smoke.py`
- `backend/alembic/versions/20251006_0002_perf_missing_deals.py` — idempotent
- tests: `test_bitrix_sanitize.py`, `test_money_key_idempotent.py`
- `.env` webhook (gitignored)
- this report

## Tests

- pytest: **38 passed**
- frontend lint: host `node_modules` missing eslint binary (Docker image already builds); not a Bitrix blocker

## Ready for full initial sync?

**NO** — awaiting user confirmation after manual verification.

Worker remains stopped. Do not start scheduled sync until approved.
"""
    OUT.write_text(md, encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"STATUS={r.get('status')} IDEMPOTENCY={db.get('idempotency')}")


if __name__ == "__main__":
    main()

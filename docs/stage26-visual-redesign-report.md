# Stage 2.6 — Visual Redesign Report

**Branch:** `stage26-visual-redesign`  
**Scope:** UX/UI only — no business logic, API, Bitrix sync, worker, sales rules engine, KPI formulas, or schema changes for design purposes.

## Goal

Replace the generic shadcn/AI-dashboard look with a calm, information-dense executive analytics UI (Linear / Attio / Stripe Dashboard level of execution — not a copy).

## Design system

| Token / rule | Implementation |
|---|---|
| Typography | Inter only (`layout.tsx` + `globals.css`); serif removed everywhere |
| Page title | `.page-title` ~28px / semibold |
| Section title | `.section-title` 14px / semibold |
| KPI values | `.kpi-value` / `.kpi-value-lg` 30–34px, tabular-nums |
| Background | Warm off-white `#f4f3f1` |
| Cards / panels | White, 9px radius, border only, no shadow |
| Brand accent | Deep muted teal `#0d5c56` |
| Semantic colors | Red / green / orange only for problem / success / warning |
| Forbidden | Gradients, glow, glass, neon, colorful card fills, blue accent strips |

**Card discipline:** Prefer typography + spacing + separators (`.panel`, KPI strips, table rows). Cards only where a surface is needed (filters shell, editor panels).

## App shell

- Sidebar ~232px, grouped nav (Обзор / Продажи / Контроль / Команда / Аналитика / Система)
- Compact Focus mark (not a tall brand block)
- Avito / AI under quiet «Скоро» footer — disabled, not a large section
- Active item: teal-tinted neutral background
- Top bar: section title + compact avatar dropdown (no large email button)
- Content padding 24–32px; denser layout

## Dashboard recomposition

1. **Hero:** Продажи (sum won) + period delta  
2. **Strip:** Активных / В работе / Новых / Выиграно / Проиграно (not 10 equal cards)  
3. **Plan/fact:** Compact empty state or progress bar  
4. **Требует внимания:** Single panel with clickable rows (count + amount)  
5. **Charts:** Sales dynamics (large) + active distribution by stage  
6. **Managers table:** Top by won sales — columns per spec (no invented performance score)

## Pages updated

| Area | Treatment |
|---|---|
| Deals | Dense explorer: filter bar, sticky header, table-first |
| Deal detail | Header meta + timeline main + right status/activities/warnings |
| Managers list | Table-first |
| Manager detail | KPI strip + attention + deals tables |
| Overdue / Stalled | Table-first; duration emphasized |
| Pipelines | Panel sections, quieter charts |
| Reports | Sectioned report via typography/spacers, not card grids |
| Sales rules | List \| editor \| preview impact (3-column config layout) |
| System / Login | Serif/shadow cleanup |

## Verification

| Check | Result |
|---|---|
| `pytest` (Docker backend, `PYTHONPATH=/app`) | **69 passed** |
| `next build` (Docker frontend image) | **PASS** (compiled + TypeScript OK) |
| Frontend lint | N/A in production image (eslint not shipped); typecheck covered by `next build` |
| Business logic / API / sync | Unchanged by Stage 2.6 UI work |

## Checklist

```
APP SHELL: PASS
DASHBOARD: PASS
DEALS: PASS
MANAGERS: PASS
PIPELINES: PASS
ATTENTION: PASS
REPORTS: PASS
SALES RULES UI: PASS
RESPONSIVE: PASS
FUNCTIONAL REGRESSION: PASS
```

### Notes on RESPONSIVE

- Desktop-first (1440–1920) with full-width content and 232px sidebar  
- Sidebar collapses to sheet on `< md`; filter bars wrap; tables scroll horizontally  
- Dense tables remain primary interaction on tablet/phone (acceptable for internal analytics)

### Notes on FUNCTIONAL REGRESSION

- Same routes, hooks, and API clients  
- Dashboard still consumes existing dashboard + managers endpoints  
- No KPI/formula or rules-engine changes in this stage  

## How to preview

```bash
docker compose up -d --build frontend
# http://localhost:13000
```

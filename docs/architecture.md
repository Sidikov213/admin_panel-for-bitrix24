# Архитектура Focus Analytics

Актуально на 2026-10-13 (после product audit + Avito Phase 1 probe).  
Стабильные теги: `bitrix-integration-stable-v1`, `focus-analytics-v1`.

## Принципы

1. **Разделение слоёв**: интеграция → репозитории → сервисы → API → UI.
2. **Read-only Bitrix**: webhook только для чтения CRM (allow-list методов).
3. **Идемпотентная синхронизация**: upsert по `bitrix_id`, snapshots по content_hash.
4. **Честная аналитика**: KPI из PostgreSQL; polling ≠ полная история событий Bitrix.
5. **Изоляция побочных jobs**: Sales Rules и Timeman не должны ломать CRM sync.
6. **Секреты только в env** / secret store — не в БД plaintext и не в Git.
7. **Расширяемость**: Avito RO probe; stubs для SLA adapter и AI без внешних вызовов.

## Компоненты

```
┌─────────────┐     ┌──────────────┐     ┌────────────┐
│  Next.js UI │────▶│  FastAPI API │────▶│ PostgreSQL │
└─────────────┘     └──────┬───────┘     └─────▲──────┘
                           │                   │
                    ┌──────▼───────┐           │
                    │ Sync Worker  │───────────┘
                    └──────┬───────┘
                           │ read-only
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         Bitrix24     Timeman      Avito API*
         (CRM)      (status RO)   (probe only)
```

\* Avito: клиент и probe-скрипты есть; product sync / UI / router — ещё нет.

## Worker architecture

Сервис `backend` (API) и `worker` (`app.workers.sync_worker`) в Docker Compose.

Цикл `scheduled_job` (интервал `SYNC_INTERVAL_MINUTES`, по умолчанию 5):

1. **Bitrix CRM sync** (если задан `BITRIX_WEBHOOK_URL`):  
   dictionaries → deals → activities  
   Full reconcile по watermark `FULL_RECONCILE_HOURS` (иначе incremental).
2. **Sales Rules evaluation** — только после успешного deal/activity sync; ошибки не откатывают sync.
3. **Timeman collector** — всегда после CRM-цикла, изолированно (`TIMEMAN_COLLECTOR_ENABLED`); сбой не влияет на CRM.

Категории CRM по умолчанию: `BITRIX_CATEGORY_IDS=1,39` (Сваи, Отложенный спрос).

## Backend packages

| Пакет / область | Роль |
|-----------------|------|
| `app/integrations/bitrix` | HTTP-клиент, sanitize, rate limit, retry, pagination, stage semantics |
| `app/services/sync_service` | Оркестрация sync, snapshots, change events |
| `app/analytics/*` | KPI, периоды, compare, attention, freshness |
| `app/services/sales_rules` | Engine, CRUD, violations, aggregates (после sync) |
| `app/services/timeman_*` / `manager_control_*` | Timeman RO poll, Manager Control V2, monitored roster |
| `app/integrations/avito` | READ ONLY client + config multi-account (Phase 1 probe) |
| `app/auth` | Argon2, sessions, CSRF, RBAC (`admin` / `viewer`) |
| `app/ai`, `app/integrations/sla` | Stubs без внешних вызовов |

## Frontend

App Router (Next.js), cookie-сессия через proxy `/api/*` → backend, TanStack Query, Recharts.

Основные поверхности: dashboard, deals, pipelines, overdue, stalled, sales-rules admin, managers, **manager-control**, reports, system.

Заглушки в навигации («Скоро»): Avito Analytics, AI-анализ.

## Avito (Phase 1)

- Credentials: только `AVITO_ACCOUNT_N_*` в локальном `.env`.
- Allow-list GET (+ token); write methods запрещены политикой клиента.
- Live capability probe: `scripts/avito_capability_probe.py` + `docs/avito-capability-probe.md`.
- Bitrix link evidence: Open Lines / `AVITOCONNECTOR` — strong heuristic, не DIRECT id join.
- **Рекомендация: hybrid** — Avito API (аккаунт, объявления, чаты, timestamps / first response) + Bitrix (менеджер, сделка, WON/LOST, выручка).

Product Avito Analytics V1 (UI / full sync) — только после явного подтверждения и успешного live re-probe.

## CI

GitHub Actions `.github/workflows/ci.yml`:

- Backend: pytest на SQLite in-memory (без реальных secrets).
- Frontend: `npm ci` → lint → build.
- Триггеры: `pull_request` и push в development branches.
- **Нет** production deploy из CI.

## Безопасность

- HTTP-only cookie `focus_session`
- CSRF double-submit `focus_csrf` + `X-CSRF-Token`
- Lockout после N неудачных логинов
- Роли `admin` / `viewer`
- Секреты только в env
- Production hardening (COOKIE_SECURE, сильные secrets, VPS) — **ещё не завершён**

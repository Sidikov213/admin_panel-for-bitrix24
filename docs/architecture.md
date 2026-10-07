# Архитектура Focus Analytics (этап 1)

## Принципы

1. **Разделение слоёв**: интеграция → репозитории → сервисы → API → UI.
2. **Read-only Bitrix**: webhook только для чтения CRM.
3. **Идемпотентная синхронизация**: upsert по bitrix_id, snapshots по content_hash.
4. **Честная аналитика**: KPI считаются из PostgreSQL; polling ≠ полная история событий.
5. **Расширяемость**: stubs для Avito, SLA adapter, AI без внешних вызовов.

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
                    ┌──────▼───────┐
                    │  Bitrix24    │
                    └──────────────┘
```

## Backend

| Пакет | Роль |
|-------|------|
| `app/integrations/bitrix` | HTTP-клиент, rate limit, retry, pagination |
| `app/services/sync_service` | Оркестрация sync, snapshots, change events |
| `app/analytics/kpi` | Расчёт показателей |
| `app/auth` | Argon2, sessions, CSRF, RBAC |
| `app/ai` | Интерфейсы без внешних вызовов |
| `app/integrations/avito`, `sla` | Заготовки адаптеров |

## Frontend

App Router, cookie-сессия через proxy `/api/*` → backend, TanStack Query, страницы дашборда/сделок/менеджеров/воронок/просрочек/stalled/отчётов/системы.

## Безопасность

- HTTP-only cookie `focus_session`
- CSRF double-submit `focus_csrf` + `X-CSRF-Token`
- Lockout после N неудачных логинов
- Роли `admin` / `viewer`
- Секреты только в env

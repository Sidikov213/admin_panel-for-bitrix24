# Отчёт этапа 1 — Focus Analytics

## 1. Что реализовано

- Backend FastAPI с авторизацией (Argon2, HTTP-only cookies, CSRF, RBAC)
- PostgreSQL-модели, Alembic-миграция
- Bitrix read-only клиент (rate limit, retry, pagination)
- Worker синхронизации (словари, сделки, активности, reconcile)
- Snapshots и наблюдаемые change events
- KPI / dashboard / deals / managers / pipelines / overdue / stalled / reports / system / targets
- Frontend Next.js со всеми страницами этапа 1
- Docker Compose (db, backend, worker, frontend)
- DEMO-режим без смешивания с production-заявлениями
- Заготовки AI / Avito / SLA adapters

## 2. Архитектура

См. [architecture.md](architecture.md). Слои разделены: integrations → repositories → services → API → UI.

## 3. Таблицы

`users`, `sessions`, `login_attempts`, `crm_managers`, `crm_pipelines`, `crm_stages`, `crm_deals`, `crm_activities`, `deal_snapshots`, `deal_change_events`, `sync_runs`, `sync_state`, `sales_targets`, `analytics_daily`.

## 4. Синхронизация

См. [sync.md](sync.md). Полная загрузка → инкремент по DATE_MODIFY с overlap → периодическая сверка.

## 5. API endpoints (`/api/v1`)

| Метод | Путь |
|-------|------|
| GET | `/health`, `/ready` |
| POST/GET | `/auth/login`, `/auth/logout`, `/auth/me` |
| GET | `/dashboard` |
| GET | `/deals`, `/deals/{id}` |
| GET | `/managers`, `/managers/{id}` |
| GET | `/pipelines` |
| GET | `/overdue` |
| GET | `/stalled?mode=no_future\|rules` |
| GET | `/reports` |
| GET | `/system` |
| CRUD | `/targets` (write — admin) |

## 6. Страницы

`/login`, `/dashboard`, `/deals`, `/deals/[id]`, `/managers`, `/managers/[id]`, `/pipelines`, `/overdue`, `/stalled`, `/reports`, `/system` + заглушки Avito / AI / Настройки.

## 7. Настоящие метрики

Новые / активные / won / lost / суммы / просроченные дела (уникальные) / без следующего дела / распределение по этапам и менеджерам / наблюдаемые смены этапов — считаются программно из БД.

## 8. Пока недоступно

Реальный Bitrix без webhook; Avito; AI; SLA из production-сервисов; утверждённый регламент stalled.

## 9. Тесты

Backend: pytest (auth, health, bitrix mocks, sync dedup, KPI, deals pagination).  
Frontend: typecheck + production build.

## 10. Запуск

См. [README.md](../README.md).

## 11. Env

См. [.env.example](../.env.example). Для реальной sync: `BITRIX_WEBHOOK_URL`, `BITRIX_PORTAL_URL`, `SESSION_SECRET`.

## 12. Этап 2 (черновик)

- Регламент stalled + календарь
- Read-only SLA adapter
- Avito accounts
- AI-анализ (после согласования)
- Наполнение `analytics_daily`
- HTTPS / reverse proxy на VPS (только после разрешения)

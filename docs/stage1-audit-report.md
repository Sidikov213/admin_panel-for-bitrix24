# Focus Analytics — Stage 1 Audit

**Дата аудита:** 2026-10-06  
**Общий результат:** **PASS WITH ISSUES**

Этап 1 работоспособен и после hardening готов к **тестовому** Bitrix webhook: clean Docker install, auth/RBAC/CSRF, KPI, Bitrix read-only adapter, perf на 5k deals, incremental activities, soft-delete missing deals, `npm ci` на Alpine. Остаточные долги: HTTPS/nginx (production), npm audit high в eslint toolchain, полный responsive matrix 1920/1440/1366.

---

## Проверенное окружение

| Компонент | Версия / значение |
|-----------|-------------------|
| OS | Windows 10 (build 26200) |
| Python (host) | 3.13.14 |
| Python (Docker backend) | 3.12-slim |
| Node | v24.13.0 |
| npm | 11.6.2 |
| PostgreSQL | 16.13 (Alpine, Docker) |
| Docker | 29.2.1 |
| Docker Compose | v5.1.0 |
| Host ports | DB `55432`, API `18000`, Frontend `13000` |
| DEMO_MODE | `false` |
| BITRIX_WEBHOOK_URL | пусто (намеренно) |

---

## Что проверено

| Блок | Статус | Как проверено | Комментарий |
|------|--------|---------------|-------------|
| Структура / слои | PASS | Обзор дерева `backend/`, `frontend/`, `docs/`, `docker-compose.yml` | integrations → repositories → services → API → UI соблюдается; сильного смешения нет |
| Secrets / gitignore | PASS | Поиск token/secret/password/webhook; `.gitignore` | `.env` в ignore; реальных Bitrix/Telegram/Avito секретов в репо нет; локальный `SESSION_SECRET` только в untracked `.env` |
| Backend startup | PASS | uvicorn / Docker `backend` healthy | Импорт приложения OK |
| PostgreSQL clean | PASS | `docker compose` volume + `alembic upgrade` в `docker_start.py` | Все 14 таблиц + `alembic_version` |
| Alembic | PASS | `alembic upgrade head` на чистой БД | Одна ветка; таблицы созданы |
| Auth cookies | PASS | HTTP suite + browser login | Argon2, HttpOnly, SameSite=Lax, session 7d; Secure зависит от `COOKIE_SECURE` |
| CSRF | PASS | POST `/targets` без/с `X-CSRF-Token` | 403 без токена; create с токеном 201 |
| RBAC | PASS | HTTP: viewer GET ok / POST targets 403; admin CRUD | Backend enforcement |
| Bruteforce | PASS | 6 неверных login → 429 | `login_attempts` + lock |
| API endpoints | PASS | `scripts/audit_full_suite.py` → **42/42 OK** | health/ready/auth/dashboard/deals/managers/pipelines/overdue/stalled/reports/system/targets |
| OpenAPI | PASS | GET `/openapi.json` | 18 paths; webhook/session_secret не в схеме |
| Deals pagination | PASS | limit=3 offset 0/3, total=10 | Серверная пагинация |
| KPI controlled dataset | PASS | Seed 10 deals → API = expected; UI dashboard совпал | active=6, won=2, lost=2, sum_active=1110, sum_won=3000, overdue unique=2, no_future=3 |
| Bitrix adapter | PASS | Code review + `pytest` mocks | Только read methods; retry limited; write methods отсутствуют |
| Sync / cursor | PASS | `test_sync_cursor.py` + code | Cursor не двигается при failed |
| Parallel sync lock | PASS (fixed) | Code + regression test | Было `hash()` (process-salted) → заменено на стабильный crc32; deals+full_reconcile общий ключ |
| Snapshots / events | PASS | unit/integration tests + code | Hash-dedup; `observed_at` vs `bitrix_event_at` |
| Overdue unique | PASS | KPI seed + API | 1 activity = 1 overdue; notifications не участвуют |
| Stalled no_future | PASS | API total=3 | Только факт отсутствия future activity |
| Stalled rules | PASS | API `enabled=false` + UI empty state | Нет demo SLA как «регламент» |
| Sales targets | PASS | CSRF + admin create + viewer deny | Frontend: «план не задан» без 0% |
| analytics_daily | PASS | Таблица есть, наполнения нет | Не используется для fake KPI |
| DEMO mode | PASS | Code + system page | Seed idempotent (fix); production `.env` DEMO=false |
| Frontend build | PASS | `npm run lint` 0; `npm run build` 0 | typecheck отдельно упал с OOM host, но build включает tsc |
| Frontend pages / auth | PASS | Browser: login → dashboard → system | KPI совпали с API; Bitrix «не настроен» |
| Responsive 390/768 | PASS | Browser device metrics + screenshots | dashboard/deals/managers; без horizontal overflow; hamburger на 390 |
| Docker Compose | PASS | `db/backend/worker/frontend` Up | Frontend Dockerfile снова `npm ci` |
| Docker health / logs | PASS WITH FIX | `compose ps` + logs | Исправлен scheduler `create_task`; skip без webhook |
| Performance 5k | PASS | `scripts/perf_seed_and_bench.py` | 5000 deals / 3000 activities; см. таблицу ниже |
| Missing deals reconcile | PASS | code + `test_missing_deals_and_activities_cursor` | soft-flag `missing_from_bitrix`, KPI/lists исключают |
| Activities incremental | PASS | code + tests | `>=DATE_MODIFY` на delta; full pull только на full reconcile |
| Health vs Ready | PASS | HTTP + code | `/ready` → 503 при DB down (тест `test_ready_db`) |
| CORS | PASS | config CSV origins | Не `*`; список из env |
| Security headers | WARNING | App-level неполный | CSP/XFO на nginx перед production (не блокер локального Bitrix) |
| npm ci / lockfile | PASS | Alpine `npm ci` exit 0 | lockfile перегенерирован; Dockerfile `RUN npm ci` |
| npm audit | WARNING (accepted) | `npm audit` → 5 high | все в `eslint-config-next` → `braces` (dev); `audit fix --force` = breaking downgrade Next ESLint — не применяли |

---

## Backend

**PASS.** FastAPI стартует в Docker и локально. Миграции на старте контейнера. HTTP suite 42/42 против live API+Postgres.

## PostgreSQL

**PASS.** Clean volume → migrations → 14 доменных таблиц. Основное приложение на PostgreSQL (тесты могут использовать SQLite/aiosqlite — только для pytest).

## Alembic

**PASS.** `upgrade head` на пустой БД успешен. Одна актуальная ветка.

## Auth / Security / RBAC

**PASS.** Cookie session + CSRF double-submit + Argon2 + role admin/viewer. Bruteforce → 429. Password не возвращается API.

## API

**PASS.** Все заявленные endpoints этапа 1 проверены реальными HTTP-запросами.

## Bitrix adapter

**PASS (read-only).** Используемые методы: `crm.deal.list`, `crm.deal.get`, `crm.activity.list`, `user.get`, `user.search`, `crm.dealcategory.list`, `crm.dealcategory.stage.list`. Write-методов в production-коде нет.

## Sync

**PASS WITH FIXES.**  
Исправлено в аудите:

1. Стабильные PG advisory lock keys (вместо `hash()`).  
2. Общий lock для `deals` / `full_reconcile`.  
3. Watermark `last_full_reconcile` только после success.  
4. APScheduler: coroutine напрямую (был `asyncio.create_task` → `RuntimeError: no running event loop`).  
5. Skip цикла если webhook не задан (без ERROR traceback).

Reconcile = `run_deals(full=True)` и реально вызывается worker'ом.

## Snapshots / Events / KPI / Overdue / Stalled / Targets

**PASS** на контролируемом датасете и тестах. UI dashboard совпал с API KPI.

## Frontend

**PASS.** Production build OK. Browser: login, dashboard (KPI), system (Bitrix not configured). Заглушки Avito/AI/Настройки в nav.

## Docker

**PASS.** Полный стек поднят. Lockfile перегенерирован; Alpine `npm ci` подтверждён (`REAL_CI_OK`); Dockerfile снова `RUN npm ci`.

## Performance (5000 deals)

**PASS** после batch SQL + indexes. Seed: 5000 deals, 3000 activities. Live API (`:18000`):

| Endpoint | ms | status |
|----------|-----|--------|
| `/dashboard` | 351 | 200 |
| `/deals?limit=50` | 30 | 200 |
| `/managers` | 31 | 200 |
| `/overdue` | 20 | 200 |
| `/stalled?mode=no_future` | 148 | 200 |

Было (controlled ~10 deals, до фикса N+1): managers ~0.9s, dashboard ~1.6s.

## Tests

| Набор | Результат |
|-------|-----------|
| Backend pytest | **34 passed**, 0 failed, 0 skipped |
| Frontend typecheck | host OOM на отдельном `tsc` (нестабильно); `next build` TypeScript OK |
| Frontend lint | exit 0 |
| Frontend build | exit 0 |
| HTTP audit suite | **42 passed**, 0 failed |

---

## Найденные проблемы

### 1. CRITICAL → FIXED: Advisory lock ключ через `hash()`
- **Описание:** разные worker-процессы получали разные lock keys (PYTHONHASHSEED).  
- **Причина:** `abs(hash(sync_type.value))`.  
- **Исправлено:** стабильный `zlib.crc32` + общий ключ для deals/full_reconcile.  
- **Файлы:** `backend/app/repositories/sync.py`, `backend/tests/test_advisory_lock_stable.py`.  
- **Проверка:** pytest + code review.

### 2. HIGH → FIXED: APScheduler `create_task` без event loop
- **Описание:** периодический sync падал `RuntimeError: no running event loop`.  
- **Причина:** `lambda: asyncio.create_task(scheduled_job())`.  
- **Исправлено:** `scheduler.add_job(scheduled_job, ...)`.  
- **Файлы:** `backend/app/workers/sync_worker.py`.  
- **Проверка:** worker logs — `Added job "scheduled_job"`, без RuntimeError.

### 3. HIGH → FIXED: `/ready` не проверял БД
- **Описание:** ready всегда ok.  
- **Исправлено:** `SELECT 1` через DbSession → 503.  
- **Файлы:** `backend/app/api/health.py`, tests.

### 4. HIGH → FIXED: cursor / reconcile watermark при failure
- **Описание:** риск пропуска данных / откладывания reconcile.  
- **Исправлено:** cursor только при `errors==0`; mark_full_reconcile только после success.  
- **Файлы:** `sync_service.py`, `sync_worker.py`, `test_sync_cursor.py`.

### 5. MEDIUM → FIXED: DEMO seed неидемпотентен
- **Исправлено:** skip если DEMO deal уже есть.  
- **Файл:** `backend/app/services/demo_data.py`.

### 6. MEDIUM → FIXED: stalled placeholder rules на dashboard
- **Исправлено:** `RULES_ENABLED=False` общий флаг; dashboard не применяет 48h/72h.  
- **Файлы:** `stalled_rules.py`, `stalled.py`, `dashboard_service.py`.

### 7. MEDIUM → FIXED: Docker frontend `npm ci` fail
- **Причина:** package-lock / optional `@emnapi` skew Windows↔Alpine.  
- **Исправлено (hardening):** lockfile перегенерирован; Alpine `npm ci` exit 0; Dockerfile снова `RUN npm ci`.  
- **Проверка:** `docker run node:20-alpine npm ci` → `REAL_CI_OK`.

### 8. MEDIUM → FIXED: CORS env list JSON decode crash
- **Исправлено:** CSV string + properties в config (ранее в сессии аудита).

### 9. LOW: Login password `min_length=8` → 422 до проверки пароля
- Короткий wrong password даёт 422, длинный wrong — 401. Не критично; зафиксировано в suite.

### 10. LOW / WARNING (accepted): npm audit 5 high
- Цепочка: `eslint-config-next` → `@next/eslint-plugin-next` → `fast-glob` → `micromatch` → `braces` (GHSA-vfj7-8cjw-p6xm).  
- Только **devDependencies** (lint); runtime Next image не тянет eslint.  
- `npm audit fix --force` предлагает `eslint-config-next@14.2.35` (breaking относительно текущего Next) — **не применяли**.  
- Перед production: обновить Next/eslint-config-next когда upstream починит braces.

### 11. WARNING: Security headers / CSP
- Не внедрены в FastAPI; ожидаются на reverse proxy **перед production**. Не блокирует локальный Bitrix.

### 12. MEDIUM → FIXED: Performance 5k / N+1
- **Исправлено:** batch aggregates в `/managers`, single-pass KPI series, indexes + `missing_from_bitrix`.  
- **Проверка:** seed 5k → dashboard 351ms, managers 31ms.

### 13. MEDIUM → FIXED: Activities sync всегда full list
- **Исправлено:** incremental `>=DATE_MODIFY`; full activity pull только при `full_reconcile`.  
- **Файлы:** `sync_service.py`, `sync_worker.py`, tests.

### 14. MEDIUM → FIXED: Full reconcile не помечал исчезнувшие deals
- **Исправлено:** soft-flag `missing_from_bitrix`; списки/KPI исключают; при повторном появлении снимается.  
- **Миграция:** `20251006_0002_perf_missing_deals`.

### 15. LOW: README порты были 3000/8000
- **Исправлено частично:** указаны 13000/18000/55432.

---

## Изменённые файлы (аудит + pre-Bitrix hardening)

- `backend/app/repositories/sync.py`, `deals.py`
- `backend/app/workers/sync_worker.py`
- `backend/app/services/demo_data.py`, `stalled_rules.py`, `dashboard_service.py`, `sync_service.py`
- `backend/app/analytics/kpi.py`
- `backend/app/api/managers.py`, `stalled.py`, `health.py`
- `backend/app/models/crm.py`
- `backend/alembic/versions/20251006_0002_perf_missing_deals.py`
- `backend/tests/test_advisory_lock_stable.py`, `test_missing_deals_and_activities_cursor.py`, …
- `backend/scripts/audit_full_suite.py`, `perf_seed_and_bench.py`
- `frontend/Dockerfile`, `.dockerignore`, `package-lock.json`
- `docker-compose.yml`, `.env.example`, `README.md`
- `docs/stage1-audit-report.md`, `docs/stage1-audit-checklist.md`

---

## Что намеренно НЕ проверялось

- Real Bitrix production webhook / массовая sync  
- Avito / AI / Production SLA adapter  
- VPS / production nginx HTTPS + CSP  
- Полный responsive matrix 1920/1440/1366  
- Production Telegram / chat IDs  

---

## Остаточные риски (перед спокойным Bitrix / production)

| # | Риск | Статус | Блокирует локальный Bitrix? |
|---|------|--------|------------------------------|
| 1 | Perf на 5k | FIXED (351/31 ms) | нет |
| 2 | npm ci / lockfile | FIXED | нет |
| 3 | npm audit 5 high | accepted (dev-only braces) | нет |
| 4 | Activities full sync | FIXED (DATE_MODIFY delta) | нет |
| 5 | Missing deals reconcile | FIXED (soft-flag) | нет |
| 6 | HTTPS / nginx / security headers | deferred → production | **нет** |
| 7 | Responsive 390/768 | smoke PASS | нет |
| 8 | Первый smoke на реальном webhook | нужен ручной прогон | да (операционно) |

---

## Готовность к тестовому Bitrix

**YES** — можно подключать **тестовый** webhook локально.

Перед подключением:

1. выставить `BITRIX_WEBHOOK_URL` (тестовый портал), `DEMO_MODE=false`;  
2. ротировать локальный `SESSION_SECRET` при необходимости;  
3. первый sync — смотреть worker logs + `/system`;  
4. full reconcile отметит исчезнувшие deals soft-flag’ом (hard delete нет — осознанно).

**Production cutover** — только после nginx/HTTPS/security headers и обновления eslint/braces chain.

# Focus Analytics

Внутренняя веб-система аналитики отдела продаж. Этап 1 — фундамент: Bitrix24 (read-only), PostgreSQL, синхронизация, KPI, веб-панель.

Production-сервисы `/opt/prosrochka` и `/opt/focusgroup-sla` **не затрагиваются**.

## Стек

| Слой | Технологии |
|------|------------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, httpx |
| Worker | APScheduler / отдельный процесс синхронизации |
| Frontend | Next.js (App Router), TypeScript, Tailwind, TanStack Query, Recharts |
| БД | PostgreSQL 16 |
| Infra | Docker Compose |

## Быстрый старт (Docker)

```bash
cp .env.example .env
# Задайте SESSION_SECRET. При наличии webhook — BITRIX_WEBHOOK_URL и BITRIX_PORTAL_URL.

docker compose up --build -d
```

Создание администратора:

```bash
docker compose exec backend python scripts/create_admin.py --email admin@company.local --password "YourSecurePassword"
```

Откройте http://localhost:13000 → `/login`  
(порты на хосте: frontend `13000`, API `18000`, PostgreSQL `55432` — чтобы не конфликтовать с другими локальными стеками).

API: http://localhost:18000/api/v1/health  
Документация API: http://localhost:18000/docs

## Локальная разработка без Docker

### PostgreSQL

Нужен PostgreSQL 16 с БД `focus_analytics`.

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/focus_analytics

python -m alembic upgrade head
python scripts/create_admin.py --email admin@company.local --password "YourSecurePassword"
uvicorn app.main:app --reload --port 8000
```

Worker (отдельный терминал):

```bash
cd backend
python -m app.workers.sync_worker
```

Демо-данные без Bitrix:

```bash
# в .env
DEMO_MODE=true
```

### Frontend

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

http://localhost:3000 — Next.js проксирует `/api/*` на backend (`API_INTERNAL_URL`).

## Переменные окружения

См. [.env.example](.env.example).

| Переменная | Назначение |
|------------|------------|
| `DATABASE_URL` | PostgreSQL (asyncpg) |
| `BITRIX_WEBHOOK_URL` | Incoming webhook Bitrix (read-only) |
| `BITRIX_PORTAL_URL` | URL портала для ссылок «Открыть в Bitrix» |
| `BITRIX_CATEGORY_IDS` | Воронки, по умолчанию `1,39` |
| `SESSION_SECRET` | Секрет сессий |
| `DEMO_MODE` | Загрузка помеченных DEMO-данных при старте API |
| `APP_TIMEZONE` | `Europe/Moscow` — границы суток для KPI |

Секреты не коммитить и не логировать.

## Тесты

```bash
cd backend
python -m pytest

cd frontend
npm run typecheck
npm run lint
npm run build
```

## Структура

```
focus-analytics/
  backend/          # FastAPI + worker + Alembic + tests
  frontend/         # Next.js панель
  docs/             # Архитектура и ограничения
  docker-compose.yml
```

## Документация

- [Архитектура](docs/architecture.md)
- [Синхронизация Bitrix](docs/sync.md)
- [Ограничения этапа 1](docs/limitations.md)
- [Отчёт этапа 1](docs/stage1-report.md)

## Важно

- Все операции с Bitrix — **только чтение**.
- Изменения через polling — **наблюдаемые**, не полная историческая лента.
- Сделки без следующего дела — **факт**, не нарушение SLA.
- Реальная синхронизация с Bitrix возможна только после заполнения `BITRIX_WEBHOOK_URL`.

# Focus Analytics

Internal sales analytics and manager control platform for Bitrix24.

## Features

- Bitrix24 read-only synchronization
- Sales dashboard
- Deals and pipeline analytics
- Overdue activity monitoring
- Deals without next activity
- Sales Rules Engine
- Manager analytics
- Manager Control / Timeman
- Weekly reports
- Plan / Fact analytics

## Stack

**Backend:** FastAPI · PostgreSQL · SQLAlchemy · Alembic

**Frontend:** Next.js · TypeScript · Tailwind · shadcn/ui · Recharts

**Infrastructure:** Docker Compose

## Quick start (Docker)

```bash
cp .env.example .env
# Set SESSION_SECRET. Add BITRIX_WEBHOOK_URL / BITRIX_PORTAL_URL for live sync.

docker compose up --build -d
```

Create an admin user:

```bash
docker compose exec backend python scripts/create_admin.py --email admin@company.local --password "YourSecurePassword"
```

Open http://localhost:13000 → `/login`

Host ports (to avoid local conflicts): frontend `13000`, API `18000`, PostgreSQL `55432`.

- API health: http://localhost:18000/api/v1/health
- API docs: http://localhost:18000/docs

## Local development

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python -m alembic upgrade head
python scripts/create_admin.py --email admin@company.local --password "YourSecurePassword"
uvicorn app.main:app --reload --port 8000
```

Worker (separate terminal):

```bash
cd backend
python -m app.workers.sync_worker
```

Demo data without Bitrix: set `DEMO_MODE=true` in `.env`.

### Frontend

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

http://localhost:3000 — Next.js proxies `/api/*` to the backend (`API_INTERNAL_URL`).

## Environment

See [.env.example](.env.example).

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL (asyncpg) |
| `BITRIX_WEBHOOK_URL` | Bitrix incoming webhook (read-only) |
| `BITRIX_PORTAL_URL` | Portal URL for “Open in Bitrix” links |
| `BITRIX_CATEGORY_IDS` | Pipelines, default `1,39` |
| `SESSION_SECRET` | Session signing secret |
| `DEMO_MODE` | Load demo fixtures on API start |
| `APP_TIMEZONE` | Day boundaries for analytics (`Europe/Moscow`) |

## Tests

```bash
# Backend (Docker)
docker compose exec -e PYTHONPATH=/app backend pytest -q

# Frontend (Docker / local with node_modules)
cd frontend
npm run lint
npm run build
```

## Security

- Credentials are stored only in `.env` (never committed).
- Bitrix integration is **read-only** (no create/update/delete via webhook).
- Secrets are never committed; `.env` / `.env.*` are gitignored (except `.env.example`).

## Project layout

```
focus-analytics/
  backend/           # FastAPI + worker + Alembic + tests
  frontend/          # Next.js app
  docs/              # Architecture and stage reports
  docker-compose.yml
```

## Documentation

- [Architecture](docs/architecture.md)
- [Bitrix sync](docs/sync.md)
- [Stage reports](docs/)

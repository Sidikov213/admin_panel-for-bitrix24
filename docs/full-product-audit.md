# Focus Analytics — полный продуктовый аудит

**Дата:** 2026-10-13  
**Ветка:** `avito-phase1-probe`  
**База стабильности:** `focus-analytics-v1` (`dc1eb8f`)  
**Теги:** `bitrix-integration-stable-v1`, `focus-analytics-v1`  
**Тип:** read-only аудит (код не менялся)

---

## Вердикт

Ядро Focus Analytics (Bitrix READ ONLY sync, дашборд, Sales Rules, Manager Control / Timeman) **готово** как внутренняя аналитическая панель.

**Avito Analytics V1 — PARTIAL:** клиент и probe есть, live API не подтверждён (нет credentials в `.env`).

Главные пробелы: **нет CI**, **нет live Avito auth**, join Avito→Bitrix пока **STRONG_HEURISTIC**, docs `architecture.md` / `limitations.md` частично устарели.

---

## Зрелость модулей

| Модуль | Статус | Комментарий |
|--------|--------|-------------|
| Bitrix READ ONLY sync | Готово | Worker, курсоры, snapshots, stage semantics |
| Dashboard / KPI / Plan-Fact | Готово | Из PostgreSQL, сравнение периодов |
| Сделки / воронки / просрочки | Готово | UI + API, категории 1 и 39 |
| Sales Rules (Регламент) | Готово | Engine + violations; comment-rules disabled |
| Manager Control / Timeman | Готово | V2: roster, stale, today workday |
| Auth / RBAC / CSRF | Готово | Argon2, session, lockout, admin/viewer |
| Отчёты / System | Готово | Weekly + sync freshness |
| Avito Analytics | Probe | Client + scripts; AUTH FAIL без secrets |
| AI-анализ | Stub | Без внешних вызовов |
| SLA-бот / Open Lines module | Вне scope | Production bot не трогать; hybrid — дизайн |

---

## Что сделано

### Интеграция и данные
- Bitrix webhook **только чтение**, allow-list методов, sanitize секретов, retry/rate limit
- Идемпотентный sync: upsert по `bitrix_id`, snapshots / change events
- 6 Alembic миграций (CRM → stalled → sales rules → Timeman → monitored roster)
- Worker: dictionaries → deals → activities → sales-rules → Timeman (изолированно)

### Аналитика и UI
- Dashboard KPI, deals, pipelines, overdue, stalled («нет следующего дела»)
- Sales Rules admin (`/admin/sales-rules`)
- Manager analytics + Manager Control board
- Reports, System / sync status
- Frontend: Next.js App Router (~16 страниц), stage26 visual redesign
- Docker Compose: frontend `13000`, API `18000`, Postgres `55432`

### Безопасность
- HTTP-only session + CSRF double-submit
- Login lockout, роли admin/viewer
- Секреты только в `.env` (gitignored)
- Avito/Bitrix клиенты с политикой READ ONLY

### Качество
- ~22 backend test modules (auth, sync, KPI, rules, Timeman, Avito fixtures)
- Документация: stage reports, sync, Avito capability probe
- Стабильные git-теги на GitHub

### Avito Phase 1 (текущая ветка)
- RO client, multi-account env design, sanitize, parse first-response
- Probe scripts + Bitrix link evidence (`AVITOCONNECTOR`, Open Lines)
- Рекомендация: **hybrid** Avito API + Bitrix для менеджера/сделки/выручки
- **STOP** до confirmation: без UI / full sync

---

## Что улучшить

| Prio | Улучшение | Зачем |
|------|-----------|-------|
| **P0** | Avito credentials + повтор live probe | Закрыть AUTH / ADS / CHATS gates |
| **P0** | CI: pytest + frontend lint/build | Сейчас нет `.github/workflows` |
| **P1** | Стабильный join Avito ↔ Bitrix deal | Сейчас heuristic по SOURCE_ID / OL |
| **P1** | Frontend smoke e2e | Нет автотестов UI |
| **P1** | Обновить `architecture.md` / `limitations.md` | Не отражают Rules / MC / Avito probe |
| **P2** | Business calendar | Для честного SLA/stalled |
| **P2** | Timeline/comments RO sync | Comment-based sales rules |
| **P2** | Production hardening | `COOKIE_SECURE`, сильные secrets |
| **P3** | AI / звонки / Telegram | Сознательно вне scope |

---

## Риски

| Риск | Уровень | Митигация |
|------|---------|-----------|
| Нет CI | Высокий | GitHub Actions на PR |
| Avito без live auth | Высокий | `.env` + re-probe |
| Polling ≠ полная история CRM | Средний | Документировано; reconcile |
| Manager ID не в Avito напрямую | Средний | Hybrid + Bitrix RESPONSIBLE_ID |
| Default Docker secrets | Средний | Перед VPS сменить |
| Stalled ≠ company SLA | Низкий | Честные формулировки UI |

---

## Стек (кратко)

- **UI:** Next.js 16 · React 19 · Tailwind 4 · TanStack Query · Recharts  
- **API:** FastAPI · SQLAlchemy async · Alembic  
- **DB:** PostgreSQL 16  
- **Jobs:** APScheduler `sync_worker`  
- **Ops:** Docker Compose · **CI отсутствует**

---

## Границы (не ломать)

- Bitrix WRITE — нет  
- FocusGroup SLA production bot — нет  
- `/opt/prosrochka` — нет  
- VPS deploy без отдельного разрешения — нет  
- `master` / стабильные теги — не переписывать  

---

## Рекомендуемый следующий шаг

1. Добавить `AVITO_ACCOUNT_1_*` в локальный `.env` и закрыть live capability probe.  
2. Включить минимальный CI.  
3. Avito Analytics V1 — **только после явного подтверждения**.  
4. Ядро CRM-аналитики менять не требуется.

---

## Итоговые gates аудита

```
CORE PRODUCT: READY
AVITO ANALYTICS V1: PARTIAL
CI/CD: NOT READY
DOCS FRESHNESS: PARTIAL
SECURITY BASELINE (local): READY
PRODUCTION HARDENING: NEEDS WORK
EXISTING SLA BOT TOUCHED: NO
BITRIX WRITE USED: NO
```

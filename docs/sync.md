# Синхронизация Bitrix24

## Режимы

1. **Dictionaries** — менеджеры, воронки, этапы.
2. **Deals** — первичная полная загрузка по `BITRIX_CATEGORY_IDS`, далее инкремент по `DATE_MODIFY` с overlap (`SYNC_OVERLAP_MINUTES`).
3. **Activities** — дела CRM (owner = deal), пересчёт агрегатов на сделках.
4. **Full reconcile** — периодическая полная сверка (`FULL_RECONCILE_HOURS`).

Интервал по умолчанию: 5 минут (`SYNC_INTERVAL_MINUTES`).

## Гарантии

- Идемпотентный upsert по `bitrix_id`.
- Snapshot только при изменении `content_hash`.
- `deal_change_events.observed_at` — время обнаружения системой.
- `bitrix_event_at` — если Bitrix дал дату события; иначе `null`.
- Advisory lock (PostgreSQL) — нет параллельных одинаковых sync.

## Ограничения

- Polling не ловит все промежуточные изменения между опросами.
- Поля, недоступные через REST webhook, остаются `null`.
- Без `BITRIX_WEBHOOK_URL` worker не получает CRM-данные; панель работает с БД / DEMO.

## Методы Bitrix (read-only)

- `crm.deal.list` / `crm.deal.get`
- `crm.activity.list`
- `crm.dealcategory.list` / `crm.dealcategory.stage.list`
- `user.search` / `user.get`

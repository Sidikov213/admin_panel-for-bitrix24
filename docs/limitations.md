# Ограничения Focus Analytics

Актуально на 2026-10-13. Stage reports (`docs/stage*-report.md`) не заменяют этот документ.

## Что уже в продукте (не ограничения)

- Bitrix read-only sync (worker + snapshots + stage semantics)
- Sales analytics / dashboard / plan-fact
- Sales Rules Engine (регламент; comment-based checks — disabled)
- Manager Control V2 + Timeman collector (RO `timeman.status`)
- Manager Control V3: configurable schedules, local calendar, workday violations, week/month/team reports (без Time Control)
- Avito Phase 1: RO client + capability/link probes (без UI / full sync) — отдельная ветка

## Не реализовано (осознанно)

- Avito Analytics V1 product (UI, непрерывный sync, SLA-метрики в дашборде)
- Live Avito auth на всех окружениях (нужны credentials в локальном `.env`)
- Прямой multi-account Avito sync в production
- Анализ звонков / транскрибация
- Реальные AI-запросы во внешние сервисы
- Запись в Bitrix (создание дел, смена стадий, сообщения)
- Telegram-рассылки
- Production deploy / VPS hardening без отдельного разрешения
- Интеграция с SQLite `/opt/prosrochka` и production FocusGroup SLA bot (`/opt/focusgroup-sla`)
- Bitrix Time Control / desktop idle-offline (осознанно; MC V3 использует только Timeman)
- Автозагрузка российского производственного календаря из внешнего сервиса (локальный calendar admin)
- Business calendar для Sales Rules / stalled SLA
- READ ONLY sync timeline/comments Bitrix (нужен для comment-based sales rules)

## Polling и данные Bitrix

| Область | Поведение |
|---------|-----------|
| Модель sync | Interval polling, не event stream |
| Семантика этапов | Без `STAGE_SEMANTIC_ID` won/lost могут показывать «недостаточно данных» |
| CLOSEDATE | Fallback на `date_modify` с пометкой в `data_quality` |
| Полная история стадий | Только наблюдаемые изменения при sync |
| Персональные контакты | Не копируются как PII-склад |
| Пропущенные правки между poll | Возможны; смягчается overlap + periodic full reconcile |

## Avito / hybrid

| Область | Статус |
|---------|--------|
| Direct Avito API | Probe-ready; live capabilities зависят от тарифа и credentials |
| Manager attribution в Avito | Не DIRECT (часто только `author_id`) |
| Связка inquiry → Bitrix deal | STRONG_HEURISTIC (`AVITOCONNECTOR`, Open Lines), не гарантированный DIRECT id |
| Рекомендация | **Hybrid**: Avito для сообщений/листингов/timestamps; Bitrix для менеджера/сделки/выручки |
| FocusGroup SLA bot | Не заменяется и не модифицируется этим проектом |

## Регламент «сделки без движения»

Правила в `StalledRulesConfig` — плейсхолдеры / черновики, не утверждённый SLA компании.  
В UI: формулировка «нет следующего запланированного дела».

Sales Rules — отдельный утверждаемый регламент; evaluation после sync.

## Ops / security gaps

- CI покрывает pytest + frontend lint/build; **production deploy из CI нет**
- Default compose secrets пригодны только для local/dev
- `COOKIE_SECURE`, сильные `SESSION_SECRET` / DB password — обязательны перед VPS
- Production hardening **не завершён**

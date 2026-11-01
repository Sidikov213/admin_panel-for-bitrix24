# Focus Analytics — master product audit

> Исторический аудит до исправлений. Актуальные изменения и результаты: [исправления 28 октября](product-repairs-2026-10-28.md).

**Дата:** 28 октября 2026, Europe/Moscow. **HEAD:** `6c34ef5b45e10dec527de8010dcb193fe46bff84`. **Ветка:** `manager-control-v3`.

Проверен текущий working tree, включая существовавшие до аудита изменения frontend. Первый проход — **AUDIT ONLY**: код продукта, миграции и прежние отчёты не исправлялись. Добавлены этот отчёт, [машиночитаемые результаты](master-product-audit-evidence.json) и [диагностический runner](audit/master_product_checks.py).

## 1. Executive summary

**Вердикт: выпуск в production заблокирован.** Продукт содержит значительную работающую реализацию, однако зелёные штатные тесты не подтверждают корректность миграций, sync и Manager Control. Найдены воспроизводимые ошибки на отдельной PostgreSQL, а не только предположения по коду.

- `pytest`: **107 passed, 0 failed, 0 skipped**, 27,63 с. Это текущая ветка, без Avito-тестов.
- Frontend: **lint exit 0**, два предупреждения; **build exit 0**, TypeScript и 18 статических страниц собраны.
- Чистый `alembic upgrade head`: **FAIL**, `DuplicateTableError: stalled_rules` на `0003`.
- Advisory lock может остаться на соединении после commit; unlock на другом соединении не освобождает его.
- Синхронизация activities не удаляет исчезнувшие activities и не пересчитывает временные флаги сделок, если upstream не прислал изменений.
- Сегодняшний Timeman snapshot создаёт нарушения за вчера, в частности «опоздание» **1440 минут**.
- При отсутствии истории отчёты возвращают `00:00:00`; отсутствие наблюдений может стать `WORKDAY_NOT_STARTED`.
- Из 55 monitored managers опрашиваются одни и те же первые 50. Department schedule не применяется через реальные service callers.
- System сообщает `data_may_be_stale=false`, когда последний sync был десять дней назад, но Bitrix доступен.
- GET от viewer создаёт roster и policy в БД. Явные admin mutation endpoints при этом защищены RBAC и CSRF.
- `backend/.env` существует, `backend/.dockerignore` отсутствует, оба backend Dockerfile делают `COPY . .`: секретный env попадёт в build context и образ.
- Avito probe существует **только в соседней ветке** `avito-phase1-probe`; в текущей — stub. Его 12 изолированных mock-тестов прошли; live auth не проверялся.

**Подтверждённых P0-инцидентов компрометации или повреждения production нет. Есть P1-блокеры выпуска.** Не объявлять Manager Control «ENGINE READY» до исправления ошибок данных. Бизнес-конфигурация также не утверждена.

### Метод и ограничения доказательств

Классификация фактов: **CONFIRMED** — непосредственно проверено; **PARTIAL** — неполно; **NOT IMPLEMENTED** — отсутствует; **BROKEN** — воспроизведено или код явно нарушает контракт; **UNKNOWN** — нет необходимого внешнего подтверждения. Матрица использует запрошенные READY / PARTIAL / MISSING / BROKEN / BLOCKED_EXTERNAL. READY относится к указанному локальному объёму проверки, не означает production approval.

Тесты и диагностика не обращались в Bitrix/Avito. Настройки тестовых процессов переопределены явно; реальные `.env` не использовались для подключения. Использован новый временный PostgreSQL 18 на `127.0.0.1:55439`, отдельный каталог в Windows Temp. Все данные синтетические. Существующие PostgreSQL, production и внешние боты не менялись. Production Compose использует PostgreSQL 16: совместимость именно с 16 этим прогоном не проверена.

Docker daemon недоступен. `docker compose config --quiet` проверен без раскрытия env. Запуск frontend для browser smoke автоматическая проверка разрешений отклонила с `blocked by policy`, без более подробной причины. Попытка не обходилась. Поэтому визуальное поведение, overflow, collapse и мобильный drawer **UNKNOWN**, даже когда CSS выглядит корректным. Playwright/Cypress suite в проекте отсутствует.

### Feature matrix

Ссылки «§N» указывают на раздел отчёта с конкретными файлами/сценариями; идентификаторы R — на risk register (§18).

| Feature | Expected | Found | Status | Evidence | Risk | Next action |
|---|---|---|---|---|---|---|
| Git release state | Всё нужное сохранено и pushed | HEAD pushed, UI dirty, Avito отдельно | PARTIAL | §2, live ls-remote | R19 | Зафиксировать проверенный UI, решить интеграцию веток |
| Bitrix policy | Strict RO | Закрытый allow-list; write calls не найдены | READY | §4, readonly tests | Низкий | Сохранить negative tests |
| Dictionaries / users / stages | Категории 1,39; semantic IDs | Реализовано | READY | sync_service, stage tests | §4 fallback | Проверить новый live sample отдельно |
| Incremental deals/activities | Без потерь окна | Overlap есть, cursor в конце, offset pagination | PARTIAL | §4, R4 | Пропуск/повтор | High-watermark начала, stable ordering |
| Full reconcile deals | Missing/reappear | Реализовано при errors=0 | PARTIAL | `_mark_missing_deals` | R2–R4 | Проверять все фазы и транзакции |
| Full reconcile activities | Удалённые не остаются | Удаления не отслеживаются | BROKEN | `empty_activity_reconcile` | R5 | Reconcile активности/владельцев |
| Snapshots / events | Текущий payload и история | A→B→A даёт latest B | BROKEN | `snapshot_reversion` | R6 | Разделить dedup и текущую версию |
| PostgreSQL models | FK, indexes, constraints | 28 таблиц; gaps и drift | PARTIAL | §5 | R1/R14 | Согласовать metadata/DDL |
| Alembic base→head | Чистая установка | DuplicateTableError | BROKEN | §5, R1 | Выпуск невозможен | Заморозить initial schema |
| Dashboard | Правдивые KPI/дельты | API есть; scope/freshness/comparison gaps | BROKEN | §6, R5/R7/R13 | Ложная аналитика | Исправить semantics метрик |
| Deals/detail | Фильтры, карточка, история | API/query/UI есть; stale derived fields | PARTIAL | §6 | R5/R6 | Исправить upstream data correctness |
| Pipelines | Текущее распределение и исходы | SQL aggregation, явное ограничение истории | READY | §6, API 200 | Browser UNKNOWN | Smoke chart/empty stages |
| Managers | KPI и drilldown | API/UI реализованы | PARTIAL | §6, API 200 | Наследует KPI errors | Проверка фильтров/периодов |
| Overdue / no future | Текущие релевантные данные | Orphan/missing activities, старые флаги | BROKEN | §6, R5/R13 | Неверные тревоги | Единые scope и time predicates |
| Reports | Корректный период/сравнение | Реализованы, наследуют KPI/targets gaps | PARTIAL | reports_service | R13 | Regression datasets |
| Targets / plan-fact | Company/manager планы | CRUD, сумма won; UI управления нет | PARTIAL | targets_service/api | R13 | Exact period/currency contract + UI |
| Sales Rules engine | CRUD, preview, dedup, history | Есть, comment checks no-op | PARTIAL | §7, штатные тесты | R5/R6/R14 | Проверить на migrated PG |
| Real sales regulation | Утверждённый регламент | Не получен | BLOCKED_EXTERNAL | §17 | Не применять выдуманные SLA | Ввод Андрея |
| Comments/timeline sync | Данные для comment rules | Нет; UI сообщает unsupported | MISSING | engine comment no-op | Честно ограничено | Отдельный RO sync после V1 |
| Timeman collector | Все monitored, isolation, dedup | 50 limit без ротации; DB failure isolation неполна | BROKEN | §8, R2/R3/R8 | Пропущенные сотрудники | Fair batching + savepoints |
| Roster | Независим от ACTIVE | Deals assignee + activity responsible + manual flags | READY | §8, inactive tests | GET mutation R11 | Сохранить mapping, вынести refresh в job |
| Stale EXPIRED board | Не «Работает», today пуст | Специальный статус/фильтрация today | READY | timeman_parse + V2 tests | History evaluator R9 | Проверить отдельные past-day facts |
| Schedules | Manager→department→default | Resolver есть, department не передают | BROKEN | `department_assignment` | R8 | Реальный department mapping |
| Calendar / absences | Нерабочие дни и overrides | Engine есть; UI ограничен, kinds расходятся | PARTIAL | §8/§10 | R10/R15 | Контракт kinds, absence CRUD/UI |
| Workday violations | 7 типов, dedup, resolution | Типы и unique есть, ложные history facts | BROKEN | §8, extra diagnostics | R9 | Observation-aware evaluation |
| Enforcement | Preview до явной даты | Даты по умолчанию нет, флаг есть | PARTIAL | workday_rules | R10 | Разделить preview/official агрегаты |
| Real work schedule/date | Утверждение компании | Не получены | BLOCKED_EXTERNAL | §17 | Официальные нарушения преждевременны | Ввод Андрея |
| MC week/month/team/CSV | No data ≠ 0, быстрый report | Фиктивный 0, O(managers×days), CSV ручной | BROKEN | §8/§12 | R10/R12/R18 | Coverage-aware totals, batching, CSV writer |
| Time Control / idle/offline | Disabled | Не реализован, явно недоступен | READY | §8 | Низкий | Не включать без источника |
| Avito RO probe | Код и тесты | В отдельной ветке, 12 tests pass | PARTIAL | §9 | Не входит в build текущей ветки | Согласованный merge + проверки |
| Avito live auth/ads/chats/messages | Подтверждённые capabilities | Не было live проверки | BLOCKED_EXTERNAL | §9 | UNKNOWN, не API FAIL | Fresh credentials и re-probe |
| Avito multi-account | ≥4 аккаунта, secret refs | Env slots N, conceptual model | PARTIAL | branch config.py | Нет product persistence | Реализовать после validation |
| Avito→Bitrix join | Shared ID | Только heuristic design/evidence | PARTIAL | §9 | Не DIRECT | Найти/проверить общий ID |
| Avito Analytics V1 | Sync, UI, metrics | Нет | MISSING | stub + нет routes/models | Будущий scope | После live API validation |
| Design system | Dark sidebar/light workspace/teal | Tokens и общие компоненты в dirty UI | PARTIAL | §10 | Browser UNKNOWN, R19 | Зафиксировать и smoke |
| Sidebar scrolling | Fixed sidebar + independent main | Нужные CSS классы есть | PARTIAL | app-shell:40/65 | Runtime UNKNOWN | Desktop/mobile scroll тест |
| Localization | Читаемые русские labels | Central labels есть, raw keys остались | BROKEN | §10, R15 | Терминология/данные UI | Дополнить mapping и контракт |
| Stage charts | 2 строки/ellipsis/full tooltip | Shared tick 13px, dynamic height | PARTIAL | category-axis-tick | Browser UNKNOWN | Проверить все длинные labels |
| Auth | Argon2/session/expiry/logout/lockout | Реализовано, локальные тесты проходят | READY | §11 | Production settings R17 | Hardening + session abuse tests |
| Backend RBAC | Admin только admin | Mutation handlers AdminUser, viewer 403 | READY | AST audit + API checks | Field validation отдельно | Route matrix tests |
| CSRF / safe GET | POST protected, GET readonly | POST protected; GET writes | BROKEN | viewer_get_mutates | R11 | Убрать GET side effects |
| Secrets | Нет Git/log/image утечек | Git не подтвердил утечку; image/log gaps | BROKEN | §11/§14 | R16/R17 | .dockerignore + redaction |
| CI | PR + development pushes | Jobs есть, branch manager-control-v3 не охвачена push | PARTIAL | ci.yml | R19 | Добавить branch policy и PG gate |
| E2E | Login/core/admin smoke | Suite отсутствует | MISSING | package/files inventory | R20 | Минимальный Playwright suite |
| Health/readiness | Process vs DB | `/api/v1/health`, `/api/v1/ready` | READY | endpoint tests | Health ≠ worker health | Отдельный worker heartbeat |
| Production config | Secure compose/env/nginx | Нет prod artifacts/fail-fast | MISSING | §14–15 | R17 | Production hardening |
| Backup/restore/HTTPS | Скрипт, restore drill, HTTPS | В репозитории нет | MISSING | §15 | Выпуск заблокирован | Создать и проверить отдельно |
| AI/calls/transcription | Не обещать работу без реализации | AI/SLA stubs, calls нет | MISSING | ai/provider.py | Scope будущего | Только после стабильного V1 |

## 2. Git state

Проверены `git status --short`, `branch -avv`, `log --graph --oneline --all`, `tag -n`, `merge-base`, `ls-tree`, **live `git ls-remote --heads origin`**. Никаких fetch/reset/checkout/merge/push не выполнялось.

| Ref | Commit | Проверка |
|---|---|---|
| manager-control-v3 / origin/manager-control-v3 | `6c34ef5` | Текущая ветка, live remote совпадает |
| avito-phase1-probe / origin/avito-phase1-probe | `16f0faf` | Соседняя ветка, не ancestor текущего HEAD |
| master, stage2-analytics, stage25-sales-rules | `1f91d36` | Local и live remote совпадают |
| stage26-visual-redesign | `dc1eb8f` | Local и live remote совпадают |
| bitrix-integration-stable-v1 | `1f91d36` | Локальный tag существует |
| focus-analytics-v1 | `dc1eb8f` | Локальный tag существует |

Общий предок текущей ветки и Avito — `cb3a062` (CI/docs). Известные commits подтверждены. Divergence с опубликованными heads нет; remote tags отдельно не запрашивались.

До аудита: **20 modified tracked frontend files**, плюс **3 untracked файла** (Git группировал два в `components/charts/`): `category-axis-tick.tsx`, `sparkline.tsx`, `metric-card.tsx`. Это около 490 additions / 330 deletions tracked diff. Они не входят в HEAD и не могут быть восстановлены обычным clone remote. Изменения не потеряны локально и были включены в lint/build. Localization `ui-labels.ts` уже в HEAD; новые sidebar/chart/redesign правки — локальные. Git release gate FAIL означает dirty/unpublished release state, а не потерю кода.

## 3. Architecture

Frontend Next.js 16.3.8/React 19.2.8/TypeScript/Tailwind 4/TanStack Query/Recharts → Next rewrite `/api/*` → FastAPI `/api/v1` → SQLAlchemy async/PostgreSQL. Worker отдельный: `backend/app/workers/sync_worker.py`. API `app/main.py` scheduler не запускает; lifespan может создать demo data только при `DEMO_MODE=true`.

Worker: dictionaries → deals → activities → sales rules при `ok` → Timeman → workday violations. APScheduler `max_instances=1`, `coalesce=True`; timeout/retry есть на HTTP-клиентах. Однако `run_sync_cycle` возвращает результат **только deal phase**, а необработанная CRM/DB ошибка пропускает последующие Timeman/evaluation вызовы. Нет общего deadline цикла, heartbeat, мониторинга stalled jobs; лимит rate per client, не на все процессы/клиенты.

API/read слой местами содержит запросы непосредственно в endpoint (`overdue`, managers, admin) — единого repository слоя нет, хотя структура каталогов это предполагает. Performance измерения ниже учитывают реальное выполнение, не название архитектурного слоя.

## 4. Bitrix

### Read-only: CONFIRMED

`backend/app/integrations/bitrix/client.py:ALLOWED_METHODS` допускает только `crm.deal.list/get`, `crm.activity.list`, `user.get/search`, `crm.dealcategory.list/stage.list`, `crm.status.list`, `crm.deal.fields`, `timeman.status`. Проверка allow-list предшествует HTTP. POST transport Bitrix REST здесь не означает business write.

Отдельный `scripts/bitrix_timeman_probe.py` имеет собственный READ_METHODS и WRITE_FORBIDDEN, проверяемые до запроса. Строки `timeman.open/close/pause/settings.set` найдены **в deny-list**, не как разрешённые вызовы. В production paths не найдено вызовов `crm.*.add/update/delete` или других write methods.

**BITRIX WRITE METHODS FOUND: NO (исполняемых разрешённых write calls). BITRIX WRITE USED: NO.** Текущая live работоспособность webhook UNKNOWN: во время аудита внешних запросов не было.

### Sync: PARTIAL / BROKEN на edge cases

- Categories defaults `1,39`; менеджеры — `user.search`; pipelines/stages ограничены configured categories.
- Stage semantics из `crm.status.list`/deal `STAGE_SEMANTIC_ID`, fallback `:WON`/`:LOSE`. Не по названию стадии. Fallback `dealcategory.stage.list` применяется при пустом результате, не при исключении основного вызова.
- Activities incremental действительно использует **`>=LAST_UPDATED`**, deals — `>=DATE_MODIFY`. Overlap default 10 минут. На обычной ошибке cursor не продвигается, это покрыто тестами.
- Но watermark записывается как **время завершения**, а не начала получения данных. При цикле длиннее overlap возможен пробел. В фильтрах `.strftime('%Y-%m-%dT%H:%M:%S')` отбрасывает UTC offset; трактовка naive времени порталом не подтверждена.
- Pagination offset-based, без заданного стабильного order для deals/activities и без верхней границы окна. Нет защиты от повторяющегося `next`; все страницы накапливаются в памяти. Уникальный `bitrix_id` защищает сохранение дублей, но не потерю строк между изменяющимися страницами.
- Full deals reconcile отмечает `missing_from_bitrix` только при errors=0, reappeared deal снимает missing. Это полезный safeguard.
- Activities full: удалённые upstream строки не удаляются/не помечаются; owner без пришедших activities не попадает в refresh. Incremental не ограничивает owners configured categories, full фильтрует их только после получения данных. Поле LAST_UPDATED локально не сохраняется.
- При истечении deadline без upstream change `has_future_activity` остаётся true. `next_deadline_at` выбирается из **всех** незавершённых дел, включая просроченные, что может скрывать `NEXT_ACTIVITY_TOO_FAR` при наличии второго будущего дела.
- Upsert read-then-write, flush без per-row savepoint. Реальная PostgreSQL ошибка слишком длинного subject вызывает **PendingRollbackError**, а не успешную изоляцию плохой строки. Аналогичный риск у collector/evaluator.
- Session-level advisory lock + commit → соединение возвращается в pool до finally/unlock. Принудительная выдача исходного соединения другому borrower воспроизвела lock leak. Ключи стабильны и deals/full разделяют ключ — это правильно, но lifetime lock неправильный.
- Snapshot `(deal_id, content_hash)` unique делает неизменный replay идемпотентным, но точное повторение payload A после B оставляет последним snapshot B; required-fields checks читают именно latest snapshot. Это воспроизведено синтетически без изменения DATE_MODIFY: если Bitrix всегда меняет DATE_MODIFY при возврате бизнес-полей, hash будет другим и этот сценарий не возникает. Live частота/достижимость такого replay UNKNOWN; current-payload invariant всё равно нарушается при точном повторе. Change events отражают только polling-наблюдения, не полную event history; переходы от NULL не пишутся из-за `old_val is not None`.

## 5. Data model и Alembic

### Полный список 28 model tables

| Область | Таблицы |
|---|---|
| Auth | `users`, `sessions`, `login_attempts` |
| CRM | `crm_managers`, `crm_pipelines`, `crm_stages`, `crm_deals`, `crm_activities` |
| История/аналитика | `deal_snapshots`, `deal_change_events`, `analytics_daily` |
| Sync / plans | `sync_runs`, `sync_state`, `sales_targets` |
| Sales rules | `stalled_rules`, `sales_rules`, `sales_rule_violations`, `sales_rule_audits`, `bitrix_deal_fields` |
| Manager Control | `manager_workday_snapshots`, `manager_workdays`, `monitored_managers` |
| V3 | `work_schedules`, `schedule_assignments`, `calendar_day_overrides`, `manager_absences`, `workday_violations`, `manager_control_policy` |

Avito/AI persistence отсутствует. `analytics_daily` модель есть; текущий dashboard считает из CRM, регулярный writer snapshot KPI не найден. Назначение таблицы не является доказательством materialized history.

PK/FK и unique по Bitrix ID есть; денежные поля `Numeric(18,2)`. Основные timestamps timezone-aware, `local_day_bounds` строит московский день и переводит в UTC. Bounds включительные: 00:00:00 … 23:59:59.999999. Naive upstream даты parser считает UTC — контракт требует отдельной проверки на live payload.

Activities используют внешние `owner_id`/`responsible_id`, без CRM FK — сознательно допускают orphan rows, следовательно analytics обязана фильтровать их. Deals имеют nullable stage/manager, что нужно учитывать при семантике и распределении. Hot indexes есть на stage/closed, manager/closed, active/no-future/missing, activity completed/deadline и history deal/observed. `date_modify`, `closedate`, activity responsible/created/completed_at не имеют соответствующего полного набора hot composite indexes.

Unique `(day_date, manager_id)` **не запрещает несколько global overrides с NULL manager** в PostgreSQL. Аналогично company targets с NULL manager и `analytics_daily` с nullable dimensions. Department assignments и один enabled default schedule не защищены достаточными DB constraints. Singleton policy — convention id=1, не database invariant. Отсутствуют CHECK для weekday/time/duration/date ranges и `manager XOR department`.

### Migration chain

Единственный head: `20261013_0007`. Цепочка полная, без missing dependencies:

`20251006_0001 → 20251006_0002 → 20261007_0003 → 0004 → 0005 → 0006 → 20261013_0007`.

На **новой пустой PostgreSQL** `upgrade head` падает: `0001_initial_schema.py:24` импортирует текущую `Base.metadata` и создаёт все 28 таблиц; `0003` повторно создаёт `stalled_rules`. `0001.downgrade` также зависит от текущих моделей и вызывает `drop_all`, а не исторически фиксированный набор DDL. Не заменять решение командой stamp на реальной БД.

Для исследования оставшейся цепочки создана **другая тестовая БД**: вручную построен synthetic pre-0003 baseline, только там выполнен stamp `0002`; реальные migrations `0003…0007` прошли. Это **не PASS чистой установки** и не рекомендованный production workaround.

`alembic check` после этого tail-теста **FAIL**: расхождения indexes/uniqueness для `bitrix_deal_fields`, `monitored_managers`, `schedule_assignments`, `stalled_rules`, `work_schedules`; partial unique `uq_srv_open_deal_rule_type` существует только в migration и видится autogenerate как лишний. Следующая автоматическая миграция может ошибочно предложить удалить важную защиту от OPEN duplicates. `ix_deal_change_events_observed_at` из `0002` также отсутствует в ORM; tail fixture его не создавал.

## 6. Analytics

| Модуль | API → implementation → frontend | Проверка и ограничения |
|---|---|---|
| Dashboard | `/dashboard` → dashboard_service + analytics/kpi → dashboard-view | API 200, KPI из DB; ошибки ниже |
| Deals | `/deals`, `/{id}` → deals_service + repositories/deals → deals-view/deal-detail-view | Параметризованные filters, bounded pagination, selectinload; data flags/history gaps |
| Managers | `/managers`, `/{id}`, `/{id}/deals` → api/managers + KPI → managers pages | List/detail API 200; поддержаны drilldowns |
| Pipelines | `/pipelines?analytics=true` → pipeline_analytics → pipelines/page | Current distribution отдельно от period outcomes; не обещает historical conversion |
| Overdue | `/overdue` → endpoint SQL + Python filtering → overdue/page | Нет полного owner/missing/category scope, full-table read |
| No future | `/stalled` → stalled/attention → stalled-view | Нет будущей активности — факт; cached boolean может устареть |
| Reports | `/reports` → reports_service → reports-view | Overview/manager table/violations; наследует KPI issues |
| Targets | `/targets` CRUD → targets_service → dashboard/reports plan-fact | Admin API есть; отдельного UI управления targets нет |
| System | `/system` → system_service → system/page | Freshness bug R7; ошибки SyncRun могут уходить пользователю |

Во frontend найдены loading/error states в перечисленных основных модулях; для deals/detail/stalled/report/MC есть пустые состояния/сообщения. Отдельные ancillary запросы, например calendar/assignments/admin и month detail, не имеют столь же полного error/retry handling. API защищены CurrentUser; admin mutations — AdminUser. Browser interactions не проверены.

**KPI не захардкожены:** поиск `431`, `805`, `610` в production backend/frontend не нашёл старых значений как KPI. Active=`closed=false`, won/lost по stage semantics + period closedate (fallback date_modify), amounts из DB. Attention использует distinct deal set для суммирования, но берёт те же потенциально stale activity facts. Все валюты без конвертации могут суммироваться; UI/target default RUB не гарантирует, что upstream все сделки рублёвые.

Проблемы корректности:

1. Global overdue KPI без manager/pipeline filter читает все activities; scoped вариант делает join к non-missing deals. Диагностика orphan activity: **global=2, pipeline1=1**, хотя все релевантные сделки только в pipeline1. Overdue page тоже не исключает missing deals.
2. Active/open opportunity/no-future/overdue/attention — **current stock**, но compute_period_kpis вычисляет их одинаково для previous period. Дельта часто искусственно 0; это не историческое сравнение.
3. Current week/month-to-date сравниваются с полной previous week/month. Например 3 дня с 7, не like-for-like; contract UI необходимо уточнить. Custom range переставляет start/end при обратном порядке; zero denominator даёт `pct_delta=None`, division-by-zero нет.
4. `observed_stage_changes`/`last_change` в KPI не ограничены переданными pipeline/manager filters. Dashboard plan_fact и rule KPI также глобальные, даже при filtered dashboard query.
5. Targets берёт **первый произвольный overlapping** plan, без exact-period choice, суммирования или prorating. Month plan может сравниваться с fact одной недели; count-targets отсутствуют.
6. KPI загружает active/won/lost rows в Python, а не делает все агрегаты в SQL; archived candidates могут расти без bound. Daily series ограничена 93 датами, но won candidates предварительно читаются за всё время.
7. PeriodPicker считает день в timezone браузера; backend — APP_TIMEZONE. В иной timezone около полуночи UI dates и server preset могут расходиться.

## 7. Sales Rules

Модель, CRUD, enabled, priorities, preview, evaluation, OPEN/RESOLVED occurrences, audit CRUD, deal/dashboard/manager/report integration реализованы. См. `services/sales_rules/{engine,crud,priority,aggregates,humanize}.py`, `api/sales_rules.py`, `models/sales_rules.py`, admin page.

При последовательной оценке существующий OPEN обновляется, исчезнувшее условие RESOLVED, повторное появление создаёт новую occurrence; тест на dedup/resolution/reopen проходит. PostgreSQL partial unique задаётся migration `0004`, не metadata. Concurrent manual `/evaluate` и worker не имеют отдельного evaluation lock: ожидается unique conflict/rollback одного процесса, не гарантированная безошибочная сериализация.

`required_comment`/`comment_max_age_minutes` хранятся, но **никогда не генерируют violations**; API сообщает `comments_capability=unsupported`, admin human description объясняет ограничение. Timeline/comments sync отсутствует. `IDLE_TOO_LONG` здесь обозначает **движение сделки**, не desktop idle менеджера.

Company regulation **NOT BUSINESS-CONFIGURED**. SalesRule по умолчанию disabled; legacy stalled rules API принудительно держит drafts disabled. Нельзя считать «idle ≥2 дня» в KPI утверждённым SLA — это hardcoded informational threshold (`analytics/kpi.py`), который следует явно обозначить или конфигурировать.

Реальная корректность engine PARTIAL: устаревшие future flags, неверный latest snapshot A→B→A и неполные field payloads дают неверные violations. Client выбирает `select=['*']`; достаточность этого набора для всех UF_* required fields не подтверждена live. Требуется проверить completeness и различать «поле не получено» от «пусто». Preview не пишет violations, но это не подтверждает полноту источника.

## 8. Manager Control

### Что подтверждено

- V1/V2 collector использует только `timeman.status`; Time Control/desktop presence/idle/offline отсутствуют и обозначены как unavailable.
- Roster не зависит от `CrmManager.is_active`: assignee deals → internal manager ID; activity `RESPONSIBLE_ID` сначала маппится по Bitrix user ID. Manual include/exclude поддержаны backend.
- `TIME_START`/`TIME_FINISH` сохраняются из payload; `observed_at` — отдельное время опроса. Content hash учитывает work_date; повторный hash обновляет observed_at, а не создаёт новую snapshot строку.
- EXPIRED/OPENED со старым start → `stale_unclosed`, label про незакрытый день. Board `_today_metrics_from_snapshot` оставляет start/end/hours пустыми. Старый EXPIRED не создаёт выдуманную прошлую history row. Для PAUSED проверка старой даты статуса менее строгая: ранний return `paused`, хотя today metrics фильтруются.
- WorkSchedule, ScheduleAssignment, CalendarDayOverride, ManagerAbsence, ManagerControlPolicy, WorkdayViolation есть и в models, и в migration `0007`.
- Семь workday types существуют: WORKDAY_NOT_STARTED, LATE_START, WORKDAY_NOT_CLOSED, EARLY_FINISH, SHORT_WORKDAY, BREAK_LIMIT_EXCEEDED, STALE_UNCLOSED_DAY. Unique occurrence manager/date/type, OPEN→RESOLVED и повторное OPEN той же строки.
- Pure rules не создают NOT_STARTED в non-working/holiday/absence. Preview до enforcement date; None date остаётся preview. Auto-November hardcode не найден.

### Ошибки и незавершённость

1. **Starvation:** `timeman_collector.py:54` возвращает `managers[:limit]`, sorting стабилен. 55 managers → одни и те же 50 каждый цикл, оставшиеся 5 никогда не опрашиваются. Observed_at один на цикл, до последовательного обхода всех менеджеров — это не точное время каждого HTTP observation.
2. **Department:** resolver умеет department_key, но board/detail/reports/evaluator вызывают его без этого параметра. UF_DEPARTMENT из raw не участвует. Department assignment сохраняется, но не работает в продукте.
3. **Cross-date facts:** `violation_evaluator.py:140` берёт latest snapshot без фильтра work_date и подставляет в любой day при отсутствии ManagerWorkday. Сегодняшний start 09:00 дал вчерашнее LATE_START 1440 мин, WORKDAY_NOT_CLOSED и SHORT_WORKDAY. При отсутствии любого snapshot вчера получает WORKDAY_NOT_STARTED. Stale/failed/no-history должны приводить к UNKNOWN, а не вине сотрудника.
4. **Reports:** отсутствующая история превращается в fact_seconds=0/fact_display=00:00:00; week plan учитывает даже будущие дни. При history_since месяц и неделя обрабатывают прошлые дни по-разному. Нет coverage-aware delta.
5. **Preview vs official:** month/team агрегируют OPEN без `is_preview=false`, возвращают общее число без разделения preview. Week возвращает is_preview на строке, но totals смешаны. Enforcement flag в модели есть; product separation неполная.
6. **Calendar UI:** отправляет `short_day`/`working_override`, backend документирует `shortened`/`working`; формы не отправляют start/end/required_minutes для сокращённого дня. Generic fallback движка может считать оба кода working, но «сокращённый день» остаётся обычной длительности.
7. **Absences:** POST backend есть, нет полноценного list/edit/delete API и frontend управления absence ranges. Roster manual API тоже не связан с отдельным admin UI.
8. **Validation:** ScheduleIn принимает timezone `Invalid/Zone`, weekday 99, время `99:99`, отрицательную длительность — HTTP 200. При использовании такого графика board/worker может упасть. `month=13` возвращает 500 вместо 422. Нет ограничения длительности report range. Ночные смены start>end не моделируются явно и не отклоняются.
9. **State history:** WorkdayViolation dedup корректен для sequential run, но повторное OPEN затирает resolved_at; отдельного audit изменений графиков/политики/повторных workday occurrences нет. Задним числом изменённый график пересчитывает исторический plan по текущей конфигурации, без versioning/effective dates.

**Итог: ENGINE PARTIAL / NOT BUSINESS-CONFIGURED.** Утверждённые working days/start/end/duration/breaks/grace/individual schedules/absence policy/enforcement date не получены. Frontend `emptySchedule` уже содержит 09–18, Пн–Пт, 480/10/10/60/30/15 минут и enabled=true. Это **developer placeholders**, не нормы компании; сохранение формы превращает их в действующую конфигурацию, хотя в БД они автоматически не seed-ятся.

## 9. Avito

В рабочем HEAD `app/integrations/avito/__init__.py` — `AvitoAdapterStub.fetch_leads() -> []`. Нет Avito client/config/parser/scripts/tests/report в текущем дереве. Branch `16f0faf` содержит эти файлы; branch не слит с MC V3. Извлечены только его модули и test file в отдельную temp directory, без env и смены ветки: **12 passed**, 0,22 с, один pytest-asyncio configuration warning.

Branch implementation: OAuth client_credentials POST `/token`, остальные calls GET-only с path prefix allow-list; retry/timeout/throttle, sanitize, self/items/chats/messages helpers, parser timestamps/direction/first response. Multi-account slots `AVITO_ACCOUNT_N_*`, name/enabled/credential_key; conceptual external_user_id и secret-store references. ≥4 slots не ограничены архитектурно; persisted product account model пока отсутствует. Dataclass credentials по умолчанию repr-ит поля — не логировать объект, желательно `repr=False` для secrets.

Проверка локальных env показала отсутствие **ключей AVITO** в двух env-файлах; значения Bitrix/session не печатались. Это не подтверждение состояния иных secret stores. Никакой live Avito auth/ads/chats/messages запрос не выполнялся: **UNKNOWN / NOT LIVE VERIFIED**, не «API FAIL».

Link probe код классифицирует Open Lines / connector evidence как **STRONG_HEURISTIC**; SOURCE_ID, activity text и UF fields дают признаки источника, а не guaranteed shared chat/deal ID. DIRECT join не найден. Исторические отчёты не заменяют повторного RO evidence capture. В текущем продукте join вообще не исполняется.

Hybrid account → listing → chat/inquiry → Bitrix deal → manager → won/lost/revenue остаётся целевой архитектурой. Inquiry/message ingestion, first-response SLA по полному потоку, unanswered, account/listing dashboards и deterministic attribution **NOT IMPLEMENTED**. Probe parser на ограниченной выборке сообщений нельзя считать production SLA engine.

## 10. Frontend

Dark fixed sidebar, light workspace, white panels, teal accent реализованы в текущих dirty файлах. Есть app-shell/sidebar-nav/top-bar/dashboard-view/metric-card/sparkline/button/table/badge/period-picker и unified CSS variables, хотя отдельные hardcoded colors остаются.

`app-shell.tsx` содержит `h-dvh overflow-hidden`; desktop aside `fixed top-0 left-0 h-dvh`; content wrapper `h-dvh overflow-x-hidden overflow-y-auto`. Collapse меняет CSS variable/sidebar width, mobile media query обнуляет margin. Sidebar **внешне fixed**, но сам nav содержит `overflow-y-auto`: на низком viewport у него отдельный scroll — это нужно согласовать с буквальным требованием «non-scrolling sidebar». Main scroll отделён в коде. Реальное отсутствие double/horizontal scroll и доступность mobile menu **UNKNOWN** по причине блокировки browser smoke.

`components/charts/category-axis-tick.tsx`: reusable tick 13px, максимум две строки, ellipsis, SVG title с full label, height `max(220, rows*44+36)`, custom tooltip. Dashboard основной stage chart не режется top8; `stageBars.slice(0,8)` относится к миниграфику active-card, managerRows тоже top8. Pipelines использует shared tick. Overlap фактически не измерен в браузере.

Localization **BROKEN по требованию «полный frontend»**:

- `ui-labels.ts` содержит запрошенные функции и SCHEDULE_FIELD_META.
- `reports-view.tsx:118` выводит sales violation `t.type` напрямую (`NO_FUTURE_ACTIVITY` и т.п.).
- Deal change events используют lowercase `stage_id`, `assigned_by_id`, `opportunity`; `getFieldLabel` знает uppercase Bitrix keys, поэтому fallback выводит internal keys.
- Calendar labels знают `short_day/working_override`, не все backend `working/weekend/shortened/day_off/vacation/sick/absence`; `getSyncTypeLabel` не знает `dictionaries`.
- Формы показывают ошибки через `Error.message`/HTTP statusText, который может быть английским. Переводы распределены между frontend labels и backend timeman/workday/humanize — источник labels не полностью централизован.

Dashboard Sales area показывает daily **counts new/won**, а рядом денежную сумму — оси/легенда должны ясно обозначать counts, чтобы не подразумевать money trend. Sparkline active-card показывает distribution по стадиям, а не историю active count; это также требует ясной семантики UI.

## 11. Security

### Auth/RBAC: локально CONFIRMED

Argon2 password hashing; случайные session tokens (32-byte token_urlsafe), в DB SHA-256 hash; TTL проверяется при get_session, user.is_active проверяется. HTTP-only session, SameSite=Lax, logout удаляет session; lockout после 5 неудачных login за 15 мин по IP+email, attempts commit до HTTPException. Штатные tests auth/audit_security проверяют эти paths. Прямые viewer admin GET/POST дали 403. Создания пользователя/изменения роли через API не найдено; frontend hiding не использовался как доказательство.

AST-проверка **24 mutating handlers**: login не требует pre-session CSRF, logout имеет validate_csrf, остальные 22 используют AdminUser и validate_csrf. Double-submit сравнивает cookie/header; CSRF token, сохранённый в session, не сверяется. Это hardening gap при cookie injection, а не доказанный standalone bypass в данной конфигурации. SESSION_SECRET **не используется** для текущих opaque sessions — слабое значение не даёт само по себе их подделать, но production fail-fast для него отсутствует.

**CSRF/safe-GET contract BROKEN:** viewer GET board вызывает `list_monitored_managers → sync_monitored_roster` и `get_or_create_policy`; get_db коммитит изменения. На чистых seed tables один GET создал 55 roster rows и policy. GET admin policy также явно commit. Move initialization/roster refresh в worker или authenticated CSRF-protected mutation; чтение должно быть read-only.

### Secrets/logs

Pattern scan проверил **366 reachable Git blobs во всех локальных refs**, включая Avito branch и UTF-16/UTF-16LE artifacts; `.env` не tracked. Финальный расширенный scan дал девять locations: synthetic webhook fixture, семь вхождений известных audit/demo passwords в diagnostic scripts и legacy credential fixture Avito. Значения не опубликованы. **Реальных внешних credentials в Git не подтверждено**, но перед production нужно исключить существование пользователей с известными audit/demo passwords; состояние пользователей реальной БД UNKNOWN. Scan не доказывает отсутствие любых произвольных секретов, удалённых unreachable objects, сторонних remote refs, старых image layers или logs. Исторические exposure по внешним сведениям этим аудитом не опровергаются.

Подтверждены gaps: backend `.env` включится в image через COPY без .dockerignore; `JSONFormatter` не редактирует Authorization/cookies/tokens и сериализует exception traceback. Synthetic Authorization credential прошёл formatter неизменённым. BitrixClientError sanitize и отключение INFO httpx есть, но general SQL/DB exceptions содержат payload/SQL и попадают в logger.exception/SyncRun.error_message; System возвращает error_message viewer. Нет подтверждения фактической утечки конкретного real secret в текущие logs; **SECRET SAFETY gate FAIL по конструкции**.

Проверенный ошибочный API `month=13` вернул generic `Internal Server Error`, без traceback в ответе. Это не отменяет утечки деталей через System persisted error fields. CSV ручной quoting не escape-ит quotes/newline/formula-prefix manager names: нужна безопасная сериализация и обработка formula injection при открытии в spreadsheet.

## 12. Tests и performance

| Проверка | Фактический результат |
|---|---|
| Backend `python -m pytest -q`, current tree | 107 passed / 0 failed / 0 skipped; 27,63 с |
| Warnings backend | 0 показано; `pytest.ini` подавляет DeprecationWarning, это не «никаких warnings в коде» |
| Avito branch unit tests, отдельно | 12 passed; 0,22 с; 1 config warning вне штатного pytest.ini |
| Frontend `npm run lint` | exit 0; 2 react-hooks/exhaustive-deps warnings в deals-view:38 |
| Frontend `npm run build` | exit 0; TypeScript PASS; warning middleware→proxy deprecated |
| `docker compose config --quiet` | exit 0 |
| `alembic heads/history` из backend cwd | Один head, 7 revisions |
| `alembic upgrade head`, fresh PG | FAIL, duplicate stalled_rules |
| Tail `0003…0007`, artificial baseline | PASS; отдельный диагностический эксперимент |
| `alembic check`, tail DB | FAIL, metadata/migration drift |
| Browser/E2E | Suite нет; runtime smoke заблокирован разрешениями |

Первый вызов Alembic из root с `-c backend/alembic.ini` не нашёл относительный `alembic/`; повтор из **backend cwd** корректно проверил цепочку. Это ошибка invocation, не отдельный defect. Python локально 3.13.14, backend Docker/CI 3.12; версии библиотек зафиксированы в evidence JSON. Frontend использовал существующий node_modules; fresh `npm ci` отдельно не выполнялся, lockfile не менялся.

Tests содержат полезные edge cases: zero-division, semantic fallback, stale EXPIRED, inactive+monitored, holidays/absence/grace/enforcement, sequential dedup, auth/CSRF. Но SQLite `create_all` не проверяет migration DDL, PG partial indexes и pool locking. Sync locks в части tests замоканы, ошибочный ID проверяет Python exception, а не abort PostgreSQL transaction. Avito tests целиком без внешнего API; это корректно для units, но не live validation. Нет multi-worker race/large roster/worker dead/partial telemetry/actual browser coverage. Локальный Node v24.13.0 отличается от Node 20 в CI/Docker; этот прогон не заменяет проверку именно container runtime.

### Измерения API

ASGITransport → настоящий FastAPI routing/auth → PostgreSQL 18. 55 managers (включая inactive), 220 deals, 220 activities, 12 длинных stage names; Timeman history отсутствует, **нет действующего default schedule**. По 3 последовательных запроса, median; SQL count включает auth. Это lower-bound локальный synthetic benchmark, не production load test и не сетевой latency.

| Endpoint | Median ms | SQL/request | HTTP |
|---|---:|---:|---|
| Dashboard | 136,5 | 62 | 200×3 |
| Deals | 21,6 | 6 | 200×3 |
| Manager list | 27,6 | 11 | 200×3 |
| Manager Control board | 171,1 | 131 | 200×3 |
| Manager CRM detail | 79,4 | 54 | 200×3 |
| Manager Control detail | 89,1 | 67 | 200×3 |
| Week report | 101,2 | 70 | 200×3 |
| Month report | 65,2 | 69 | 200×3 |
| Team month-to-date report | **3228,3** | **3289** | 200×3 |
| Pipelines | 46,8 | 21 | 200×3 |
| Reports | 97,1 | 54 | 200×3 |

Team report делает day loop для CRM и nested manager×day schedule lookup. При configured schedules добавятся calendar/absence queries; unlimited start/end усиливает риск. `_latest_snapshots` загружает всю history всех monitored managers и выбирает latest в Python. Analytics и rules также делают full-table Python aggregation. Нужны batch fetch schedules/overrides/absence/workdays, bounded periods, SQL aggregate + latest-per-manager, EXPLAIN на реальном обезличенном объёме.

### Минимальный E2E gate

Login/logout/expired session; dashboard loaded/error/empty/freshness; deals filters/detail; MC stale/no-history/department/preview; viewer direct admin route/API denial; admin valid mutation + missing-CSRF rejection; desktop sidebar scroll/collapse; mobile 375px/768px и 1440px длинные русские labels. Тесты должны запускаться на fresh **migrated PostgreSQL**, synthetic data, без Bitrix/Avito secrets.

## 13. CI

`.github/workflows/ci.yml` реально содержит backend pytest и frontend npm ci → lint → build. PR triggers есть, auto-production deploy нет. Push patterns `master`, stage branches/`stage*`, `avito*` **не включают `manager-control-v3`** и не включают любую arbitrary development/codex branch. Поэтому утверждение «development push покрыт» не полностью верно.

CI не тестирует Alembic upgrade/check, PostgreSQL-specific behavior, Docker build/start, E2E и secret inclusion в images. Live remote branch HEAD проверен, но историю GitHub Actions runs/успех последнего remote CI отдельно не запрашивали — UNKNOWN.

## 14. Docker

Compose содержит frontend/backend/worker/db, PostgreSQL volume и health dependency; API/worker разделены, scheduler только в worker. Frontend multi-stage standalone production runner non-root, backend uvicorn без reload, dev server в Docker CMD не используется. Backend/worker запускаются root; requirements включают test tooling; `COPY . .` забирает env/venv/cache без backend .dockerignore. API entrypoint требует migrations, поэтому fresh compose start упрётся в R1.

Default DB user/password — developer defaults, DB/backend/frontend ports опубликованы без loopback bind; dev/prod compose separation отсутствует. `docker-compose.audit.yml` — только overrides локальных портов, **не production configuration**. Worker healthcheck/restart policy не найдены. Frontend compose передаёт build arg NEXT_PUBLIC_BITRIX_PORTAL_URL, но Dockerfile его не объявляет; ссылка может зависеть от runtime backend portal field — проверить fallback для всех consumers.

Compose syntax PASS. Образы не собирались и контейнеры не запускались: Docker daemon недоступен. Не утверждать Docker runtime PASS по одному config.

## 15. Production

| Артефакт / gate | Статус |
|---|---|
| `.env.production.example` | NOT IMPLEMENTED |
| `docker-compose.prod.yml` | NOT IMPLEMENTED |
| nginx template / TLS configuration | NOT IMPLEMENTED |
| backup script / retention / restore drill | NOT IMPLEMENTED |
| production runbook / controlled rollback | NOT IMPLEMENTED как завершённый комплект |
| settings fail-fast для prod | NOT IMPLEMENTED |
| Liveness/readiness | CONFIRMED `/api/v1/health` и `/api/v1/ready`; naked `/health`/`/ready` не объявлены |
| secure cookies mandatory | BROKEN как production gate: COOKIE_SECURE=false default, startup guard нет |
| SESSION_SECRET / DB / CORS validation | PARTIAL: настройки есть, strong/non-wildcard enforcement нет |
| no reload / no dev CMD | CONFIRMED для Dockerfiles |
| Worker observability/restart | PARTIAL / недостаточно |
| Production deployed / VPS hardening | UNKNOWN; в этом аудите не выполнялось |

Readiness делает SELECT 1, при DB exception возвращает 503; liveness не зависит от Bitrix — правильно. Healthcheck контейнера backend смотрит liveness, не доказывает DB/schema или работоспособность worker. `SESSION_SECRET` сам по себе сейчас не участвует в opaque session validation; требование его проверки не заменяет secure cookies, TLS и защиту DB.

## 16. Documentation audit

Старые документы **не изменены**. Ниже конкретные устаревшие/противоречивые sections, которые нельзя использовать как доказательства текущего состояния.

| Документ / section | Расхождение |
|---|---|
| `full-product-audit.md`, «Вердикт», «Качество», «Что улучшить», final gates | «ядро готово», «нет CI», «Avito текущая ветка», AUTH FAIL без secrets, 6 migrations — не соответствуют текущим фактам. CI есть; Avito соседняя ветка; 7 migrations; auth UNKNOWN; есть воспроизведённые блокеры |
| `architecture.md`, «Компоненты», packages, «Avito (Phase 1)» | Показывает Avito client/scripts как состав текущего продукта; фактически stub |
| `architecture.md`, «Worker architecture» | Утверждает sales evaluation после успешного deal/activity sync и Timeman всегда после CRM; код проверяет только deals, unhandled CRM exception пропускает Timeman |
| `architecture.md`, «CI» | Development push формулировка шире реальных branch filters |
| `limitations.md`, «Что уже в продукте» / «Ops» | Отдельная Avito ветка и отсутствие hardening указаны честно; не перечислены актуальные data/race/migration issues |
| `limitations.md`, «Персональные контакты не копируются как PII-склад» | Менеджер raw и deal snapshot сохраняют upstream dictionaries/payloads. Политику fields/redaction/retention нельзя выводить из этой фразы; нужен inventory, без публикации PII |
| `stage2-analytics-report.md`, «DB migrations», «Tests», checklist | Исторические 59 tests и PASS не подтверждают fresh current migrations; current stock comparisons/targets требуют исправления |
| `stage2-sales-rules-report.md`, «Tests», checklist | 69 tests — historical, current 107; sequential dedup не доказывает PG concurrency или correctness latest payload |
| `manager-control-v1-report.md`, «Data collection», final gates | Исторические 80 tests и collector PASS не покрывают >50 roster и DB failures |
| `manager-control-empty-diag.md`, «Why UI looks empty», «Fix directions» | Историческая диагностика V1: часть направлений уже реализована V2; старые 5-person факты не текущий live аудит |
| `manager-control-v2-fix-report.md`, «Verification», gates | 91 tests исторические; roster visibility исправлена, но collector completeness >50 не подтверждена |
| `manager-control-v3-report.md`, «Schedule engine» | «No defaults hardcoded» противоречит frontend emptySchedule placeholders; department priority не end-to-end. «No violations без schedule» имеет исключение STALE |
| `manager-control-v3-report.md`, «Migration», «Tests», «Honest limitations» | Не проверяет clean chain; missing-history test относится к preview, не totals и historical evaluator |
| `avito-capability-probe.md` | Отсутствует в текущей ветке, есть в Avito; live статус только UNKNOWN. Исторические данные не revalidated |

## 17. External blockers — EXTERNAL INPUT REQUIRED

От Андрея необходимы отдельные утверждённые документы/параметры, а не developer defaults:

1. **Avito:** перечень минимум всех используемых аккаунтов, название/направление, Client ID/Client Secret через защищённое хранилище, API enabled/tariff/scopes, account→Bitrix/Open Line mapping. Старые exposed credentials не переиспользовать. Live probe только после получения свежих credentials, без send/write.
2. **Sales regulation:** stages, required actions per stage, stage SLA, next-contact/repeated-contact rules, required fields, comment requirements, loss reasons/rules и deferred-demand rules. Определить рабочее/календарное время, exceptions и момент начала enforcement.
3. **Work schedules:** рабочие дни/start/end/required duration, breaks, late/early tolerances, индивидуальные и department schedules, absence/vacation/sick/day-off policy, timezone/overnight shifts, enforcement start date. Согласовать, что отсутствие telemetry ≠ нарушение.
4. **Sales targets:** company/per-manager, деньги или количество, currency, week/month, exact periods, prorating и overlap policy. Сейчас count targets не реализованы.

Проверка синтетической БД ничего не утверждает о реальных business settings в существующей рабочей БД; её содержимое не инспектировалось. В отсутствие утверждения статусы real regulation/schedule/enforcement/targets — **NO / BLOCKED_EXTERNAL**, не «в базе гарантированно пусто».

## 18. Risks — register

### P0 critical

Подтверждённых P0-инцидентов нет. Production не исследовался и не менялся. Это не разрешение на выпуск: P1 ниже являются release blockers.

### P1 high

| ID | Problem | Impact | Evidence | Recommended fix / acceptance |
|---|---|---|---|---|
| R1 | Dynamic metadata в initial migration; ORM/DDL drift | Fresh install невозможен; опасный autogenerate | `0001:24`, fresh PG DuplicateTableError; §5 | Заморозить исторический DDL; проверить fresh upgrade и реальный upgrade существующей базы на копии; согласовать partial indexes. Без stamp-workaround |
| R2 | Session advisory lock переживает commit, unlock на другом connection | Зависшие jobs / пропуск sync; reentrant locks ломают ожидания | repositories/sync:28–38; extra borrow test оставил 1 lock | Lock ownership на выделенном connection до unlock либо transaction locks с корректной транзакцией; multi-session PG test |
| R3 | Ошибка одной SQL строки abort-ит всю transaction; CRM failure пропускает Timeman | Потеря цикла и freshness, bootstrap может завершиться | `db_row_failure_isolation=PendingRollbackError`, `crm_exception_skips_timeman=false called` | Savepoint/rollback на строку, безопасное сохранение failure; finally/independent jobs; failed activity не может дать full success |
| R4 | Cursor завершения + offset pagination + stripped TZ | Пропущенные обновления при долгом цикле/движении страниц | sync_service:132/150/209/247, client.call_paginated | Start high-watermark, stable order/keyset где возможно, explicit timezone; long-cycle fixture |
| R5 | Deleted/expired activities не reconcile-ятся, cached future flag не обновляется | Ложные no-future/overdue/SLA/KPI | `empty_activity_reconcile`: row=1, future=true после empty full | Soft-delete/missing activities + refresh всех relevant owners; вычислять future по now; regression deadline-crossing/deletion |
| R6 | Snapshot A→B→A сохраняет latest B | Ложный required-field violation и история | `snapshot_reversion`: expected A, got B | Current raw payload/version отдельно от occurrence history; сохранить повторное состояние корректно |
| R7 | Worker dead, но System «fresh»; dashboard берёт любой successful phase | Пользователь доверяет старой/частичной аналитике | `dead_worker_freshness=false`; dashboard_service:54 | Freshness по обязательным phase watermarks + failed/stuck/heartbeat; per-manager freshness |
| R8 | >50 managers starvation; department assignment не исполняется | Часть сотрудников не контролируется, неверные нормы | `collector_starvation`, `department_assignment` | Ротация/курсор или bounded полный обход; department resolution из данных менеджера |
| R9 | Latest snapshot без work_date + missing telemetry как absence | Ложные персональные нарушения, 1440 мин опоздания | `today_snapshot_applied_yesterday`, `no_observation_violation` | Facts только той даты, coverage/failed/stale UNKNOWN; не считать отсутствие наблюдения виной; historical fixtures |
| R10 | Missing history=0; preview смешан с official; future-day delta | Недостоверные отчёты о труде | mc_reports:168/242/334, JSON results | Nullable facts + coverage; separate preview/official totals; period-to-date semantics |
| R16 | Backend env попадает в image | Возможная выдача webhook/session credentials каждому с доступом к image | backend/.env exists; Dockerfile:9; нет .dockerignore | Минимальный COPY/context, исключить env/venv/logs; проверить image layers без публикации значений |
| R17 | Production defaults без fail-fast, нет TLS/backups/runbook | Небезопасный и невосстановимый deployment | config.py + compose + отсутствующие artifacts | Отдельный prod config, secure cookies, secret validation, private DB, TLS, backup+restore drill |

### P2 medium

| ID | Problem | Impact | Evidence | Recommended fix |
|---|---|---|---|---|
| R11 | GET мутирует roster/policy | Нарушен readonly/CSRF contract, races при чтении | viewer GET: 0→55 roster, policy=1 | Read paths без flush/commit side effects; init/job/mutation |
| R12 | N×days SQL, unbounded report range, all-history snapshots | Медленные отчёты, resource exhaustion | team 3289 SQL/3,23 с на малых данных | Batch queries, диапазон ≤ согласованного max, SQL latest rows, performance budget |
| R13 | KPI scope/current-vs-history/targets/currency inconsistencies | Неверные финансовые/операционные сравнения | §6, orphan 2 vs1 | Формальный metric contract, matched previous period, scope-filtered aggregates, currency validation |
| R14 | Weak validation/DB invariants и concurrent rule evaluation | HTTP 500, ambiguous schedules/global overrides, duplicate races | Schedule invalid HTTP200, month13 HTTP500, nullable uniques | Pydantic validators + CHECK/partial unique + evaluate serialization |
| R15 | Incomplete labels, calendar kinds, absence UI, defaults без маркировки | Пользователь видит internal values/сохраняет фиктивные нормы | §8/§10, admin page:27, reports-view:118 | Contract enums, Russian mapping, явные draft placeholders, absence workflow |
| R18 | Logs/System errors без общей sanitization, unsafe CSV | SQL/PII/секреты в logs, CSV повреждения/formula execution | JSONFormatter synthetic test; System _run_dict; manual CSV | Structured allow-list errors, sanitize до хранения/вывода, csv.writer + formula protection |
| R19 | Dirty UI, Avito ветка отдельно, CI push пропускает текущую ветку | Невоспроизводимый release и проверки не того кода | §2/§9/§13 | Review/commit UI, осознанная integration, CI branch policy; не merge вслепую |
| R20 | Tests создают schema напрямую, нет E2E/PG races | Зелёный CI пропускает release blockers | conftest, migration и adversarial results | PG migration integration gate + локальные regression tests + smoke E2E |

### P3 low

| ID | Problem | Impact | Evidence | Recommended fix |
|---|---|---|---|---|
| R21 | Устаревшие отчёты/gates и test counts | Ошибочные ожидания готовности | §16 | Явно пометить исторические отчёты, связать с новым audit |
| R22 | 2 hook lint warnings, deprecated middleware, дубли colors/maps | Технический долг, future upgrade risk | lint/build, §10 | Малые отдельные cleanup changes после correctness |

## 19. Recommended roadmap

1. **Закрыть P1 до любого deploy.** Начать с R1/metadata drift и изолированного PG migration gate, затем lock/transaction/full-cycle status, activity freshness/reconcile/snapshot reversion, MC data correctness. Не исправлять миграции существующих баз без inventory их actual revision/schema и restore-tested копии. Это архитектурно значимое изменение, описанное здесь до реализации.
2. Вынести GET writes, внедрить validation/constraints и исправить отчёты/no-history/preview. Ввести safe structured errors и .dockerignore; обеспечить deterministic release tree/CI.
3. Получить утверждённые inputs от Андрея (регламент/графики/targets/Avito mapping). Исправленные engine readiness и business approval — разные gates.
4. Настроить MC schedules/calendar/absences сначала в preview; сравнить факты, получить дату enforcement. Не переносить UI placeholders автоматически.
5. Настроить Sales Rules по утверждённому регламенту, preview и audit изменения. Comments оставить unavailable до sync.
6. Настроить exact-period company/manager targets, currency и count/money semantics.
7. Получить fresh Avito credentials через secret store; осознанно интегрировать probe branch; live RO capability re-probe по всем аккаунтам.
8. Только после успешной validation проектировать Avito Analytics V1: incremental sync/dedup, account/listing/chat model, response coverage, доказанный join. Без shared ID явно сохранять heuristic confidence.
9. Добавить и прогнать E2E smoke, PG concurrency/migration tests, responsive/long-label checks; установить performance budget и проверить anonymized production-size dataset.
10. Production hardening: отдельные env/compose, non-root/minimal images, DB isolation, TLS, readiness, worker heartbeat/alerts, backup+restore drill, rollback/runbook. Ротация credentials — если подтверждено историческое раскрытие.
11. Отдельно согласованный controlled deploy и observation period. Здесь deploy **не выполняется**.
12. AI/comments/calls/transcription только после стабильного V1 и определения источников/требований.

## 20. Final gates

Для бинарных PASS/FAIL **FAIL может означать неподтверждённый gate**, а не доказанную поломку. UNKNOWN вынесен в пояснения: browser runtime, live APIs, фактический production и approved business configuration. PASS Auth/RBAC/Read-only относится к проверенному локальному объёму; Pipelines PASS — API/query/build, не завершённому browser E2E.

```text
GIT STATE: FAIL
BITRIX READ ONLY: PASS
BITRIX SYNC: FAIL
DATABASE: FAIL
ALEMBIC: FAIL

DASHBOARD: FAIL
DEALS: FAIL
PIPELINES: PASS
REPORTS: FAIL

SALES RULES ENGINE: PARTIAL
REAL SALES REGULATION CONFIGURED: NO

TIMEMAN COLLECTOR: FAIL
MANAGER CONTROL V3: PARTIAL
REAL WORK SCHEDULE CONFIGURED: NO
ENFORCEMENT CONFIGURED: NO

AVITO PROBE: PARTIAL
AVITO LIVE AUTH VERIFIED: NO
AVITO ANALYTICS PRODUCT: NO
AVITO→BITRIX JOIN: STRONG_HEURISTIC

AUTH: PASS
RBAC: PASS
CSRF: FAIL
SECRET SAFETY: FAIL

UI LOCALIZATION: FAIL
DESIGN SYSTEM: PASS
SIDEBAR SCROLL: FAIL
RESPONSIVE: FAIL

CI: FAIL
BACKEND TESTS: PASS
FRONTEND LINT: PASS
FRONTEND BUILD: PASS
E2E: NO

PRODUCTION CONFIG: NO
BACKUPS: NO
NGINX/HTTPS: NO
PRODUCTION DEPLOYED: NO

EXISTING SLA BOT TOUCHED: NO
PROSROCHKA TOUCHED: NO
BITRIX WRITE USED: NO
```

Пояснения: sidebar/responsive FAIL = **UNKNOWN runtime**, нужные CSS конструкции найдены. Design system PASS = наличие общих компонентов/tokens и успешная сборка, не визуальная приёмка. Git/CI FAIL = unpublished working tree и push coverage gap. Avito STRONG_HEURISTIC = historical/probe classification, **не готовый текущий join**. Real configs NO = утверждение/применение не подтверждены; реальные БД не инспектировались. Production deployed NO = этим аудитом не выполнен и не подтверждён; состояние внешнего VPS UNKNOWN. Backup/HTTPS NO = реализация в репозитории отсутствует, внешняя инфраструктура UNKNOWN.

### Три независимые оценки

- **CORE PRODUCT READINESS: 58/100.** Инженерная оценка: surfaces/API 35/40, correctness 10/30, verification 13/30. Высокое покрытие функций снижено воспроизведёнными sync/MC/migration ошибками и отсутствием browser/PG CI gates.
- **BUSINESS CONFIGURATION READINESS: 0/100.** Ни один из четырёх пакетов утверждённых company inputs (регламент, графики/enforcement, targets, Avito accounts/mapping) не подтверждён. Framework не засчитывается как business configuration.
- **PRODUCTION READINESS: 15/100.** Есть production frontend build, разделение API/worker и health/readiness; clean install, secrets-in-image, безопасный prod config, restore/HTTPS/monitoring gates не закрыты. Это checklist assessment, не статистическая вероятность.

Оценки не усредняются. **STOP после аудита:** fixes/refactor/merge/deploy не выполнялись; следующие изменения должны опираться на этот risk register и повторять воспроизводимые проверки.

### Воспроизводимость диагностики

`docs/audit/master_product_checks.py` требует `FOCUS_AUDIT_DATABASE_URL` на **новую пустую localhost PostgreSQL** с именем `focus_audit_*`, отказывается от non-empty DB, создаёт только synthetic data через metadata и проверяет локальные endpoints. Это диагностический runner, **не replacement для migration test**, и часть его checks намеренно демонстрирует дефекты, а не считается ещё одним «зелёным pytest suite». `FOCUS_AUDIT_OUTPUT` задаёт путь JSON; не направлять его на существующие файлы. Extra adversarial scenarios и результат migration экспериментов сохранены в evidence JSON. Никакие значения реальных credentials в артефакты не включены.

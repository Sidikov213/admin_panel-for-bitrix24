/**
 * Centralized Russian UI labels for API/internal values.
 * Internal keys (API, DB, enums) stay unchanged — only display text is localized.
 */

const SEVERITY_LABELS: Record<string, string> = {
  low: "Низкий",
  medium: "Средний",
  high: "Критично",
  critical: "Критично",
  info: "Информация",
  warning: "Предупреждение",
};

const STATUS_LABELS: Record<string, string> = {
  open: "Открыто",
  OPEN: "Открыто",
  resolved: "Устранено",
  RESOLVED: "Устранено",
  closed: "Закрыто",
  CLOSED: "Закрыто",
  working: "Работает",
  paused: "Пауза",
  not_started: "Рабочий день не начат",
  stale_unclosed: "Старый незакрытый рабочий день",
  expired: "Рабочий день не закрыт",
  no_data: "Нет данных",
  unknown_bitrix: "Неизвестный статус Bitrix",
  success: "Успешно",
  failed: "Ошибка",
  pending: "Ожидание",
  running: "Выполняется",
  idle: "Простой",
  unknown: "Неизвестно",
  enabled: "Включено",
  disabled: "Выключено",
  active: "Активен",
  inactive: "Неактивен",
  on: "Вкл",
  off: "Выкл",
};

const VIOLATION_TYPE_LABELS: Record<string, string> = {
  WORKDAY_NOT_STARTED: "Рабочий день не начат",
  LATE_START: "Опоздание",
  WORKDAY_NOT_CLOSED: "Рабочий день не завершён",
  EARLY_FINISH: "Ранний уход",
  SHORT_WORKDAY: "Недостаточно отработано",
  BREAK_LIMIT_EXCEEDED: "Превышено время перерывов",
  STALE_UNCLOSED_DAY: "Старый незакрытый рабочий день",
};

const CALENDAR_KIND_LABELS: Record<string, string> = {
  holiday: "Праздник / выходной",
  short_day: "Сокращённый день",
  working_override: "Рабочий день (переопределение)",
};

const WORKER_STATUS_LABELS: Record<string, string> = {
  running: "Работает",
  stopped: "Остановлен",
  idle: "Простой",
  unknown: "Неизвестно",
  healthy: "Норма",
  unhealthy: "Сбой",
  error: "Ошибка",
};

/** Schedule form field keys → Russian label + optional helper. */
export const SCHEDULE_FIELD_META: Record<
  string,
  { label: string; helper?: string }
> = {
  start_time: { label: "Начало рабочего дня" },
  end_time: { label: "Конец рабочего дня" },
  required_minutes: {
    label: "Норма рабочего времени, мин",
    helper: "Количество рабочих минут без учёта перерывов",
  },
  late_grace_minutes: {
    label: "Допустимое опоздание, мин",
    helper: "Опоздание в пределах этого порога не считается нарушением",
  },
  early_finish_grace_minutes: {
    label: "Допустимый ранний уход, мин",
  },
  max_break_minutes: {
    label: "Максимум перерывов, мин",
  },
  not_started_threshold_minutes: {
    label: "Считать день не начатым через, мин",
    helper: "После планового начала, если день ещё не открыт",
  },
  not_closed_grace_minutes: {
    label: "Считать день не закрытым через, мин",
    helper: "После планового окончания, если день ещё открыт",
  },
  enabled: { label: "Активен" },
  is_default: { label: "График по умолчанию" },
};

export function getSeverityLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return SEVERITY_LABELS[value] ?? SEVERITY_LABELS[value.toLowerCase()] ?? value;
}

export function getStatusLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return STATUS_LABELS[value] ?? STATUS_LABELS[value.toLowerCase()] ?? value;
}

export function getViolationLabel(type: string | null | undefined): string {
  if (!type) return "—";
  return VIOLATION_TYPE_LABELS[type] ?? type;
}

export function getCalendarKindLabel(kind: string | null | undefined): string {
  if (!kind) return "—";
  return CALENDAR_KIND_LABELS[kind] ?? kind;
}

export function getWorkerStatusLabel(value: string | null | undefined): string {
  if (!value) return "Неизвестно";
  return WORKER_STATUS_LABELS[value] ?? WORKER_STATUS_LABELS[value.toLowerCase()] ?? value;
}

export function getEnabledLabel(enabled: boolean | null | undefined): string {
  if (enabled === true) return "Включено";
  if (enabled === false) return "Выключено";
  return "—";
}

export function getBoolActiveLabel(enabled: boolean | null | undefined): string {
  if (enabled === true) return "Активен";
  if (enabled === false) return "Неактивен";
  return "—";
}

export const VIOLATION_TYPES = Object.keys(VIOLATION_TYPE_LABELS);

/** Common Bitrix / CRM field codes → Russian display. */
const FIELD_NAME_LABELS: Record<string, string> = {
  TITLE: "Название",
  STAGE_ID: "Этап",
  OPPORTUNITY: "Сумма",
  CURRENCY_ID: "Валюта",
  ASSIGNED_BY_ID: "Ответственный",
  CATEGORY_ID: "Воронка",
  CLOSEDATE: "Дата закрытия",
  BEGINDATE: "Дата начала",
  COMMENTS: "Комментарий",
  SOURCE_ID: "Источник",
  PROBABILITY: "Вероятность",
};

const DYNAMICS_KEY_LABELS: Record<string, string> = {
  new_deals: "Новые сделки",
  won: "Выиграно",
  lost: "Проиграно",
  sum_won: "Сумма выигранных",
  active_pipeline_count: "Активных в воронке",
  active_pipeline_amount: "Сумма активных",
  overdue: "Просроченные",
  no_future_activity: "Без следующего дела",
  deals_requiring_attention: "Требуют внимания",
};

export function getFieldLabel(fieldName: string | null | undefined): string {
  if (!fieldName) return "—";
  return FIELD_NAME_LABELS[fieldName] ?? fieldName;
}

export function getDynamicsKeyLabel(key: string): string {
  return DYNAMICS_KEY_LABELS[key] ?? key.replace(/_/g, " ");
}

const METRIC_DRILL_LABELS: Record<string, string> = {
  active: "Активные сделки",
  new: "Новые сделки",
  won: "Выигранные",
  lost: "Проигранные",
  overdue: "Просроченные",
  no_future: "Без следующего дела",
  sum_won: "Сумма выигранных",
  sum_active: "Сумма активных",
};

export function getMetricDrillLabel(key: string | null | undefined): string {
  if (!key) return "Сделки";
  return METRIC_DRILL_LABELS[key] ?? getDynamicsKeyLabel(key);
}

/** Human label for sync_type codes from worker. */
const SYNC_TYPE_LABELS: Record<string, string> = {
  incremental: "Инкрементальная",
  full_reconcile: "Полная сверка",
  deals: "Сделки",
  activities: "Дела",
  bootstrap: "Начальная",
  timeman: "Timeman",
};

export function getSyncTypeLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return SYNC_TYPE_LABELS[value] ?? value.replace(/_/g, " ");
}

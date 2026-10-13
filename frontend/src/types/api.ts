export type UserRole = "admin" | "viewer";

export interface User {
  id: number;
  email: string;
  role: UserRole;
  is_active: boolean;
}

export interface KpiDefinition {
  label: string;
  formula: string;
  source: string;
}

export interface MetricDelta {
  current: number;
  previous: number;
  abs_delta: number;
  pct_delta: number | null;
}

export interface KpiMetrics {
  period_start: string;
  period_end: string;
  timezone?: string;
  new_deals_count: number;
  active_deals_count: number;
  won_count: number;
  lost_count: number;
  sum_active_opportunity: number;
  sum_won_opportunity: number;
  overdue_activities_unique: number;
  open_overdue: number;
  deals_by_stage: Record<string, number>;
  deals_by_stage_named?: NamedCount[];
  deals_by_manager: Record<string, number>;
  deals_by_manager_named?: NamedCount[];
  deals_by_pipeline?: PipelineCount[];
  observed_stage_changes: number;
  last_observed_deal_change: string | null;
  deals_without_future_activity_count: number;
  deals_without_future_activity_amount?: number;
  deals_without_future_activity_label?: string;
  deals_without_movement_count?: number;
  money_requiring_attention?: number;
  deals_requiring_attention_count?: number;
  money_requiring_attention_label?: string;
  series_daily?: DailySeriesPoint[];
  definitions?: Record<string, KpiDefinition>;
  data_quality?: {
    insufficient_stage_semantics?: boolean;
    won_used_date_modify_fallback?: number;
    note?: string | null;
  };
  computed_at?: string;
}

export interface NamedCount {
  stage_id?: number | null;
  manager_id?: number | null;
  name: string;
  count: number;
}

export interface PipelineCount {
  category_id: number | null;
  name: string;
  count: number;
}

export interface DailySeriesPoint {
  date: string;
  new: number;
  won: number;
}

export interface Freshness {
  last_updated_at?: string | null;
  last_attempted_at?: string | null;
  age_minutes?: number | null;
  stale_after_minutes?: number;
  is_stale?: boolean;
  sync_failed?: boolean;
  warning?: string | null;
}

export interface PlanFact {
  plan_set: boolean;
  plan: number | null;
  fact: number;
  percent: number | null;
  remaining: number | null;
  label: string;
  fact_metric?: string;
  currency?: string;
}

export interface AttentionCategory {
  label: string;
  count: number;
  items: AttentionItem[];
  note?: string;
}

export interface AttentionItem {
  deal_id: number;
  bitrix_id?: number;
  title: string;
  manager?: string | null;
  manager_id?: number | null;
  stage?: string | null;
  amount?: number | null;
  fact: string;
  category?: string;
  bitrix_url?: string | null;
}

export interface DashboardResponse {
  kpis: KpiMetrics;
  comparison?: {
    current_period: { start: string; end: string; preset?: string };
    previous_period: { start: string; end: string; preset?: string };
    metrics: Record<string, MetricDelta>;
  };
  attention?: {
    title: string;
    money_requiring_attention: { label: string; deals_count: number; amount: number };
    categories: Record<string, AttentionCategory>;
    objective_signals?: {
      label: string;
      categories: Record<string, AttentionCategory>;
    };
    business_rule_violations?: {
      label: string;
      total?: number;
      enabled_rules?: number;
      note?: string | null;
      categories?: Record<string, AttentionCategory>;
    };
    rules_note?: string;
  };
  rule_violations?: {
    deals_with_violations: number;
    high_severity_violations: number;
    amount_under_violations: number;
    open_violations: number;
    enabled_rules: number;
    note?: string | null;
  };
  plan_fact?: PlanFact;
  freshness?: Freshness;
  charts: {
    series_daily?: DailySeriesPoint[] | null;
    deals_by_stage: NamedCount[] | Record<string, number> | null;
    deals_by_manager: NamedCount[] | Record<string, number> | null;
    deals_by_pipeline?: PipelineCount[] | null;
  };
  recent_changes: DealChangeEvent[];
  problem_deals: ProblemDeal[];
  sync?: {
    last_deals_sync: { at?: string } | null;
    latest_run_status: string | null;
    latest_run_finished_at: string | null;
    data_may_be_stale: boolean;
    stale_note: string | null;
  };
  meta?: {
    period_start: string;
    period_end: string;
    preset?: string;
    computed_at?: string;
  };
}

export interface DealChangeEvent {
  id?: number;
  deal_id: number;
  field_name: string;
  old_value: string | null;
  new_value: string | null;
  observed_at: string;
  bitrix_event_at: string | null;
  note?: string | null;
}

export interface ProblemDeal {
  deal_id: number;
  bitrix_id?: number;
  title: string;
  stalled?: boolean;
  reason?: string | null;
  no_future_activity?: boolean;
  no_future_activity_label?: string;
  manager?: string | null;
  stage?: string | null;
  last_observed_activity_at?: string | null;
  fact?: string;
  amount?: number | null;
}

export interface StageBrief {
  id: number;
  name: string;
  bitrix_id: string;
  semantics?: string | null;
}

export interface ManagerBrief {
  id: number;
  name: string;
  last_name: string;
  bitrix_id: number;
  is_active?: boolean;
}

export interface ManagerListItem extends ManagerBrief {
  active_deals_count?: number;
  new_deals_count?: number;
  won_count?: number;
  lost_count?: number;
  sum_active_opportunity?: number;
  sum_won_opportunity?: number;
  overdue_activities_unique?: number;
  deals_without_future_activity_count?: number;
  no_future_share?: number;
  observed_stage_changes?: number;
  open_violations?: number;
  high_severity_violations?: number;
  resolved_violations?: number;
  violation_rate?: number | null;
  new_deals_delta?: MetricDelta;
  period?: { start: string; end: string; preset?: string };
}

export interface ManagerDetail {
  manager: ManagerBrief;
  kpis: KpiMetrics;
  deals: Array<{
    id: number;
    bitrix_id: number;
    title: string;
    closed: boolean;
    opportunity: number | null;
    stage_name: string | null;
    has_future_activity: boolean;
    date_modify: string | null;
  }>;
  comparison?: {
    current_period: { start: string; end: string };
    previous_period: { start: string; end: string };
    metrics: Record<string, MetricDelta>;
  };
  plan_fact?: PlanFact;
  problem_deals?: Array<{
    id: number;
    bitrix_id: number;
    title: string;
    stage_name: string | null;
    opportunity: number | null;
    fact: string;
    bitrix_url: string | null;
  }>;
  meta?: { period_start: string; period_end: string; preset?: string };
}

export interface Deal {
  id: number;
  bitrix_id: number;
  title: string;
  category_id: number | null;
  stage_id: number | null;
  assigned_by_id: number | null;
  opportunity: string | number | null;
  currency_id: string | null;
  date_create: string | null;
  date_modify: string | null;
  closedate: string | null;
  closed: boolean;
  has_future_activity: boolean;
  open_activities_count: number;
  next_deadline_at: string | null;
  last_observed_activity_at: string | null;
  stage_changed_observed_at?: string | null;
  observed_at?: string | null;
  stage: StageBrief | null;
  assigned_manager: ManagerBrief | null;
}

export interface Activity {
  id: number;
  bitrix_id: number;
  type_id: number | null;
  subject: string | null;
  responsible_id: number | null;
  owner_type_id: number | null;
  owner_id: number | null;
  created: string | null;
  deadline: string | null;
  completed: boolean;
  completed_at: string | null;
}

export interface TimelineItem {
  at: string;
  kind: string;
  title: string;
  detail: string | null;
  is_observed: boolean;
  note: string | null;
}

export interface SnapshotItem {
  id: number;
  observed_at: string;
  content_hash: string;
  payload_summary: Record<string, unknown> | null;
}

export interface DealDetail extends Deal {
  activities: Activity[];
  current_activities?: Activity[];
  overdue_activities?: Activity[];
  future_activities?: Activity[];
  change_events: DealChangeEvent[];
  timeline?: TimelineItem[];
  snapshots?: SnapshotItem[];
  pipeline_name?: string | null;
  no_future_activity_label: string | null;
  bitrix_url: string | null;
  hours_without_observed_movement: number | null;
  violations?: {
    active: Array<{
      id: number;
      rule_id: number;
      rule_name: string;
      type: string;
      severity: string;
      status: string;
      details?: string | null;
      current_value?: string | null;
      threshold?: string | null;
      detected_at?: string | null;
      resolved_at?: string | null;
    }>;
    resolved: Array<{
      id: number;
      rule_id: number;
      rule_name: string;
      type: string;
      severity: string;
      status: string;
      details?: string | null;
      current_value?: string | null;
      threshold?: string | null;
      detected_at?: string | null;
      resolved_at?: string | null;
    }>;
  };
}

export interface DealListResponse {
  items: Deal[];
  total: number;
  offset: number;
  limit: number;
}

export interface PipelineStage {
  id: number;
  bitrix_id: string;
  name: string;
  sort: number;
  semantics: string | null;
  deals_count?: number;
  amount?: number;
  share_of_active_pipeline?: number;
  share_of_all_active?: number;
}

export interface Pipeline {
  id: number;
  bitrix_id: number | string;
  name: string;
  sort: number;
  stages: PipelineStage[];
}

export interface PipelineAnalyticsItem {
  id: number;
  bitrix_id: number;
  name: string;
  current_distribution: {
    active_deals: number;
    active_amount: number;
    share_of_all_active: number;
    stages: PipelineStage[];
    note?: string;
  };
  period_outcomes: {
    period_start: string;
    period_end: string;
    new_deals: number;
    won: number;
    lost: number;
    sum_won: number;
    observed_stage_changes: number;
    note?: string;
  };
  funnel: Array<{ name: string; value: number; amount: number }>;
}

export interface PipelineAnalyticsResponse {
  pipelines: PipelineAnalyticsItem[];
  all_active_deals: number;
  distinction?: Record<string, string>;
  period?: { start: string; end: string; preset?: string };
}

export interface OverdueActivity {
  id: number;
  bitrix_id: number;
  subject: string | null;
  owner_id?: number | null;
  deadline: string | null;
  is_overdue?: boolean;
  overdue_label?: string;
  manager?: string | null;
  manager_id?: number | null;
  deal_id?: number | null;
  deal_title?: string | null;
  pipeline_category_id?: number | null;
  stage?: string | null;
  amount?: number | null;
  bitrix_url?: string | null;
}

export interface OverdueResponse {
  items: OverdueActivity[];
  total: number;
  groups?: Record<string, OverdueActivity[]> | null;
  note?: string;
}

export interface StalledDealItem {
  deal_id: number;
  bitrix_id?: number;
  title: string;
  amount?: number | null;
  reason: string | null;
  last_observed_activity_at: string | null;
  stage_changed_observed_at: string | null;
  has_future_activity: boolean;
  no_future_activity?: boolean;
  label_no_future?: string | null;
  time_without_future_task?: string | null;
  hours_without_observed_movement?: number | null;
  stage?: string | null;
  pipeline_category_id?: number | null;
  manager?: string | null;
  manager_id?: number | null;
  bitrix_url?: string | null;
  disclaimer?: string;
}

export interface StalledResponse {
  mode?: string;
  enabled?: boolean;
  items: StalledDealItem[];
  total: number;
  sum_opportunity?: number;
  summary_label?: string | null;
  disclaimer?: string;
  rules_config?: {
    min_hours_since_last_activity: number | null;
    min_hours_since_stage_change: number | null;
    require_no_future_activity: boolean | null;
    note: string;
  };
}

export interface StalledRulesResponse {
  items: Array<Record<string, unknown>>;
  total: number;
  engine_ready: boolean;
  rules_applied: boolean;
  note: string;
}

export interface ReportsResponse {
  title?: string;
  period?: { start: string; end: string; preset?: string };
  previous_period?: { start: string; end: string };
  overview?: Record<string, unknown>;
  problems?: Record<string, number>;
  regulation_violations?: {
    configured?: boolean;
    enabled?: boolean;
    message?: string;
    open?: number;
    new_during_period?: number;
    resolved?: number;
    by_type?: Array<{ type: string; count: number }>;
    by_manager?: Array<{ manager_id?: number | null; manager_name: string; count: number }>;
    label?: string;
  };
  managers?: Array<Record<string, unknown>>;
  dynamics?: Record<string, MetricDelta>;
  freshness?: Freshness;
  kpis?: KpiMetrics;
  report?: KpiMetrics;
}

export interface SyncRunInfo {
  id: number;
  sync_type: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  items_processed?: number;
  errors_count?: number;
  error_message?: string | null;
  duration_seconds?: number | null;
}

export interface SystemStatus {
  demo_mode: boolean;
  bitrix_configured: boolean;
  bitrix_reachable: boolean;
  bitrix_portal_url?: string | null;
  category_ids?: number[];
  sync_interval_minutes?: number;
  last_deals_sync: { at?: string } | string | null;
  last_activities_sync: { at?: string } | string | null;
  last_dictionaries_sync: { at?: string } | string | null;
  data_may_be_stale?: boolean;
  stale_note?: string | null;
  checked_at?: string;
  latest_sync_run: SyncRunInfo | null;
  recent_sync_runs?: SyncRunInfo[];
  integrations?: Record<string, { status: string; note?: string; read_only?: boolean }>;
  worker_status?: string;
  db_ok?: boolean;
  last_successful_sync?: string | null;
  last_attempted_sync?: string | null;
  deal_cursor?: { at?: string } | null;
  activity_cursor?: { at?: string } | null;
  last_full_reconcile?: { at?: string } | null;
  duration_last_sync_seconds?: number | null;
  errors_24h?: number;
  failed_runs_24h?: number;
  totals?: {
    deals: number;
    activities: number;
    snapshots: number;
    change_events: number;
  };
  freshness?: Freshness;
  webhook_configured?: boolean;
}

export type PeriodType = "week" | "month" | "quarter" | "year";

export interface SalesTarget {
  id: number;
  manager_id: number | null;
  period_type: PeriodType;
  period_start: string;
  period_end: string;
  amount: string | number;
  currency: string;
}

export interface TimemanFreshness {
  last_updated_at?: string | null;
  last_updated_local?: string | null;
  age_minutes?: number | null;
  stale?: boolean;
  ok?: boolean;
  history_since?: string | null;
  history_since_note?: string;
  time_control?: {
    available: boolean;
    label: string;
    status: string;
    features?: string[];
  };
}

export interface ManagerControlScheduleBrief {
  configured: boolean;
  label?: string;
  id?: number;
  name?: string;
  start?: string | null;
  end?: string | null;
  is_working?: boolean;
}

export interface ManagerControlViolationBadge {
  type: string;
  label: string;
  severity: string;
  is_preview?: boolean;
}

export interface ManagerControlLimitations {
  time_control: boolean;
  note: string;
}

export interface ManagerControlPolicyBrief {
  enforcement_start_date?: string | null;
}

export interface ManagerControlListItem {
  id: number;
  bitrix_id: number;
  name: string;
  last_name: string;
  display_name: string;
  bitrix_user_active?: boolean;
  monitored?: boolean;
  status_normalized: string;
  status_label: string;
  is_stale_unclosed?: boolean;
  stale_since_date?: string | null;
  stale_since_label?: string | null;
  status_tooltip?: string | null;
  time_start?: string | null;
  time_finish?: string | null;
  duration_seconds?: number | null;
  duration_display?: string | null;
  time_leaks_seconds?: number | null;
  time_leaks_display?: string | null;
  today_metrics_available?: boolean;
  crm_actions_today: number;
  overdue_activities: number;
  no_future_activity: number;
  last_timeman_poll_at?: string | null;
  last_timeman_poll_local?: string | null;
  has_snapshot?: boolean;
  workday_today_row?: boolean;
  schedule?: ManagerControlScheduleBrief;
  violations_count?: number;
  violation_badges?: ManagerControlViolationBadge[];
  has_violations?: boolean;
  /** @deprecated use today_metrics_available / has_snapshot */
  workday_available?: boolean;
}

export interface ManagerControlListResponse {
  date: string;
  timezone: string;
  freshness: TimemanFreshness;
  policy?: ManagerControlPolicyBrief;
  limitations?: ManagerControlLimitations;
  items: ManagerControlListItem[];
  total: number;
}

export interface ManagerControlCrmActivity {
  created_deals: number;
  changed_deals: number;
  completed_activities: number;
  stage_changes: number;
  opportunity_changes: number;
  overdue_activities: number;
  no_future_activity: number;
}

export interface ManagerControlWeekRow {
  date: string;
  workday_available: boolean;
  missing_reason?: string | null;
  note?: string | null;
  status_normalized?: string | null;
  status_label?: string | null;
  time_start?: string | null;
  time_finish?: string | null;
  duration_seconds?: number | null;
  duration_display?: string | null;
  time_leaks_seconds?: number | null;
  time_leaks_display?: string | null;
  crm_activity?: Partial<ManagerControlCrmActivity> & { crm_actions_today?: number };
  show_as_zero_workday?: boolean;
}

export interface ManagerControlScheduleToday {
  configured: boolean;
  label?: string;
  id?: number;
  name?: string;
  planned_start?: string | null;
  planned_end?: string | null;
  required_minutes?: number | null;
  is_working?: boolean;
  kind?: string | null;
}

export interface ManagerControlViolationRow {
  type: string;
  label: string;
  severity: string;
  threshold?: string | number | null;
  actual?: string | number | null;
  details?: Record<string, unknown> | null;
  is_preview?: boolean;
  detected_at?: string;
  resolved_at?: string | null;
}

export interface ManagerControlDetail {
  id: number;
  bitrix_id: number;
  name: string;
  last_name: string;
  display_name: string;
  bitrix_user_active?: boolean;
  date: string;
  timezone: string;
  freshness: TimemanFreshness;
  policy?: ManagerControlPolicyBrief;
  limitations?: ManagerControlLimitations;
  today: {
    current_status: {
      status_normalized: string;
      status_label: string;
      is_stale_unclosed?: boolean;
      stale_since_date?: string | null;
      stale_since_label?: string | null;
      tooltip?: string | null;
      has_snapshot?: boolean;
      last_timeman_poll_at?: string | null;
      last_timeman_poll_local?: string | null;
    };
    schedule?: ManagerControlScheduleToday;
    workday: {
      available: boolean;
      note?: string | null;
      time_start?: string | null;
      time_finish?: string | null;
      duration_seconds?: number | null;
      duration_display?: string | null;
      time_leaks_seconds?: number | null;
      time_leaks_display?: string | null;
    } | null;
    timeline: Array<{
      kind: string;
      label: string;
      at?: string;
      duration_seconds?: number | null;
      duration_display?: string | null;
      source?: string;
    }>;
    crm_activity: ManagerControlCrmActivity;
    violations?: {
      open: ManagerControlViolationRow[];
      resolved: ManagerControlViolationRow[];
    };
  };
  week: ManagerControlWeekRow[];
}

export interface ManagerControlWeekReportRow {
  date: string;
  plan?: {
    schedule_name?: string | null;
    is_working?: boolean;
    start?: string | null;
    end?: string | null;
    required_minutes?: number | null;
    kind?: string | null;
  } | null;
  schedule_configured?: boolean;
  time_start?: string | null;
  time_finish?: string | null;
  duration_display?: string | null;
  time_leaks_display?: string | null;
  late_minutes?: number | null;
  shortfall_minutes?: number | null;
  violations?: Array<{
    type: string;
    label: string;
    state: string;
    severity: string;
    is_preview?: boolean;
  }>;
  crm_actions?: number;
  no_historical_data?: boolean;
  missing_data_label?: string | null;
}

export interface ManagerControlWeekReport {
  manager_id: number;
  period: { start: string; end: string };
  rows: ManagerControlWeekReportRow[];
  totals: {
    working_days: number;
    days_with_data: number;
    plan_minutes: number;
    fact_seconds: number;
    fact_display: string;
    delta_minutes: number;
    late_count: number;
    not_closed_count: number;
    open_violations: number;
  };
  freshness: TimemanFreshness;
  limitations?: ManagerControlLimitations;
}

export interface ManagerControlMonthReport {
  manager_id: number;
  period: { start: string; end: string; year: number; month: number };
  plan_working_days: number;
  marked_days: number;
  plan_minutes: number;
  fact_seconds: number;
  fact_display: string;
  delta_minutes: number;
  late_starts: number;
  early_finishes: number;
  not_closed: number;
  not_started: number;
  total_open_violations: number;
  violations_by_type: Record<string, number>;
  history_since?: string | null;
  freshness: TimemanFreshness;
}

export interface ManagerControlTeamReportItem {
  id: number;
  display_name: string;
  working_days_plan: number;
  marked_days: number;
  plan_minutes: number;
  fact_seconds: number;
  fact_display: string;
  delta_minutes: number;
  late_starts: number;
  not_closed: number;
  open_violations: number;
  crm_actions: number;
}

export interface ManagerControlTeamReport {
  period: { start: string; end: string };
  items: ManagerControlTeamReportItem[];
  total: number;
  freshness: TimemanFreshness;
  csv_headers?: string[];
}

export interface McWorkSchedule {
  id?: number;
  name: string;
  timezone?: string;
  weekdays?: number[];
  start_time: string;
  end_time: string;
  required_minutes?: number | null;
  late_grace_minutes?: number | null;
  early_finish_grace_minutes?: number | null;
  max_break_minutes?: number | null;
  not_started_threshold_minutes?: number | null;
  not_closed_grace_minutes?: number | null;
  enabled?: boolean;
  is_default?: boolean;
  note?: string | null;
}

export interface McScheduleAssignment {
  id: number;
  schedule_id: number;
  manager_id?: number | null;
  department_key?: string | null;
  note?: string | null;
}

export interface McCalendarOverride {
  id: number;
  day_date: string;
  kind: string;
  manager_id?: number | null;
  start_time?: string | null;
  end_time?: string | null;
  required_minutes?: number | null;
  label?: string | null;
  note?: string | null;
}

export interface McControlPolicy {
  enforcement_start_date?: string | null;
  severity_by_type?: Record<string, string>;
  note?: string | null;
}

export interface McSchedulePreview {
  manager_id: number;
  schedule_id: number;
  days_with_data: number;
  message?: string;
  late_starts: number;
  not_closed: number;
  short_days: number;
  not_started: number;
  total_violations: number;
}

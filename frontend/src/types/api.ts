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
  deals_without_future_activity_label?: string;
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

export interface DashboardResponse {
  kpis: KpiMetrics;
  charts: {
    series_daily?: DailySeriesPoint[] | null;
    deals_by_stage: NamedCount[] | Record<string, number> | null;
    deals_by_manager: NamedCount[] | Record<string, number> | null;
    deals_by_pipeline?: PipelineCount[] | null;
  };
  recent_changes: DealChangeEvent[];
  problem_deals: ProblemDeal[];
  comparison?: {
    period_start: string;
    period_end: string;
    metrics: Record<ComparedMetric, MetricDelta>;
  };
  sync?: {
    last_deals_sync: { at?: string } | null;
    latest_run_status: string | null;
    latest_run_finished_at: string | null;
    data_may_be_stale: boolean;
    stale_note: string;
  };
  meta?: {
    period_start: string;
    period_end: string;
    pipeline_id?: number | null;
    manager_id?: number | null;
    computed_at?: string;
  };
}

export type ComparedMetric = "new_deals_count" | "won_count" | "lost_count" | "sum_won_opportunity";

export interface MetricDelta {
  previous: number;
  delta: number;
  delta_pct: number | null;
}

export interface DealChangeEvent {
  id?: number;
  deal_id: number;
  deal_title?: string | null;
  field_name: string;
  field_label?: string;
  old_value: string | null;
  new_value: string | null;
  old_label?: string | null;
  new_label?: string | null;
  observed_at: string;
  bitrix_event_at: string | null;
  note?: string | null;
}

export interface ProblemDeal {
  deal_id: number;
  bitrix_id?: number;
  title: string;
  opportunity?: number | null;
  stalled: boolean;
  reason: string | null;
  no_future_activity: boolean;
  no_future_activity_label?: string;
  manager?: string | null;
  stage?: string | null;
  last_observed_activity_at?: string | null;
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
  telegram_chat_id?: string | null;
}

export interface NotificationStatus {
  telegram_configured: boolean;
  team_chat_configured: boolean;
  enabled: boolean;
  days: string;
  time: string;
  timezone: string;
  stale_days: number;
  managers_with_chat: number;
  last_sent: {
    date?: string;
    at?: string;
    team_sent?: boolean;
    managers_sent?: number;
    errors?: number;
  } | null;
}

export interface DigestPreview {
  date: string;
  team: string;
  managers: Array<{ manager_id: number; name: string; has_chat: boolean; text: string }>;
}

export interface DigestSendResult {
  status: "sent" | "skipped" | "failed";
  reason?: string;
  date?: string;
  team_sent?: boolean;
  managers_sent?: number;
  errors?: string[];
}

export interface ManagerListItem extends ManagerBrief {
  active_deals_count?: number;
  new_deals_count?: number;
  won_count?: number;
  sum_active_opportunity?: number;
  sum_won_opportunity?: number;
  overdue_activities_unique?: number;
  deals_without_future_activity_count?: number;
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

export interface DealDetail extends Deal {
  activities: Activity[];
  change_events: DealChangeEvent[];
  no_future_activity_label: string | null;
  bitrix_url: string | null;
  hours_without_observed_movement: number | null;
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
}

export interface Pipeline {
  id: number;
  bitrix_id: number | string;
  name: string;
  sort: number;
  stages: PipelineStage[];
}

export interface OverdueActivity {
  id: number;
  bitrix_id: number;
  subject: string;
  owner_id: number | null;
  deadline: string | null;
  is_overdue: boolean;
}

export interface OverdueResponse {
  items: OverdueActivity[];
  total: number;
}

export interface StalledDealItem {
  deal_id: number;
  bitrix_id?: number;
  title: string;
  reason: string | null;
  last_observed_activity_at: string | null;
  stage_changed_observed_at: string | null;
  has_future_activity: boolean;
  no_future_activity?: boolean;
  label_no_future?: string | null;
  hours_without_observed_movement?: number | null;
  stage?: string | null;
  manager?: string | null;
  disclaimer?: string;
}

export interface StalledResponse {
  mode?: string;
  enabled?: boolean;
  items: StalledDealItem[];
  total: number;
  disclaimer?: string;
  rules_config?: {
    min_hours_since_last_activity: number | null;
    min_hours_since_stage_change: number | null;
    require_no_future_activity: boolean | null;
    note: string;
  };
}

export interface ReportsResponse {
  report: KpiMetrics;
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

export type SalesTargetInput = {
  manager_id: number | null;
  period_type: PeriodType;
  period_start: string;
  period_end: string;
  amount: string;
  currency?: string;
};

export type PlanStatus = "done" | "on_track" | "at_risk" | "behind" | "missed" | "not_started" | "early";

export interface TargetProgress {
  target_id: number;
  manager_id: number | null;
  manager_name: string | null;
  period_type: PeriodType;
  period_start: string;
  period_end: string;
  currency: string;
  plan: number;
  fact: number;
  won_count: number;
  percent: number;
  expected: number;
  forecast: number;
  forecast_percent: number;
  forecast_reliable: boolean;
  forecast_in_days: number;
  remaining: number;
  days_total: number;
  days_elapsed: number;
  days_left: number;
  per_day_needed: number | null;
  status: PlanStatus;
  active: boolean;
}

export interface TargetProgressResponse {
  on: string;
  items: TargetProgress[];
  note: string;
}

export interface DurationStats {
  median_days: number | null;
  avg_days: number | null;
  count: number;
}

export interface FunnelResponse {
  pipeline: { category_id: number; name: string };
  period_start: string;
  period_end: string;
  manager_id: number | null;
  funnel: Array<{
    stage_id: string;
    name: string;
    reached: number;
    conversion_from_prev: number | null;
    conversion_from_start: number | null;
    kind?: "won";
  }>;
  stage_time: Array<
    DurationStats & { stage_id: string; name: string; current_count: number; current_median_days: number | null }
  >;
  summary: {
    created: number;
    won: number;
    lost: number;
    win_rate: number | null;
    won_amount: number;
    avg_won_amount: number | null;
    cycle_won: DurationStats;
    cycle_lost: DurationStats;
  };
  losses: Array<{ stage_id: string; name: string; count: number; share: number }>;
  managers: Array<{
    manager_id: number;
    name: string;
    created: number;
    won: number;
    lost: number;
    win_rate: number | null;
    won_amount: number;
    cycle_won_median_days: number | null;
  }>;
  data_quality: { source: "bitrix" | "mixed" | "observed" | "none"; history_coverage: number | null; note: string | null };
  definitions: Record<string, string>;
  computed_at: string;
}

export type SlaUnit = "work_hours" | "work_days" | "calendar_days";

export interface SlaRule {
  stage_bitrix_id: string;
  stage_name: string;
  category_id: number;
  pipeline_name: string;
  sort: number;
  threshold: number | null;
  unit: SlaUnit;
  reaction_stage: boolean;
  source: "default" | "custom" | "none";
  label: string;
  tracked: boolean;
}

export interface SlaRulesResponse {
  items: SlaRule[];
  units: Record<SlaUnit, string>;
  work_calendar: { hours: string; workdays: number[]; holidays: string[] };
}

export interface StuckDeal {
  deal_id: number;
  bitrix_id: number;
  title: string;
  opportunity: number | null;
  manager_id: number | null;
  manager: string | null;
  stage_id: string;
  stage: string;
  pipeline: string;
  rule: string;
  unit: SlaUnit;
  in_stage_seconds: number;
  limit_seconds: number | null;
  over_seconds: number;
  over_ratio: number | null;
  stuck: boolean;
  in_stage_since: string;
  in_stage_since_source: "bitrix" | "observed" | "created";
  last_movement_at: string;
  last_activity: { type: string; subject: string | null; at: string; completed: boolean } | null;
  has_future_activity: boolean;
  next_deadline_at: string | null;
  bitrix_url: string | null;
}

export interface StuckResponse {
  items: StuckDeal[];
  total: number;
  stuck_total: number;
  open_total: number;
  by_stage: Array<{
    stage_id: string;
    name: string;
    pipeline: string;
    category_id: number;
    sort: number;
    rule: string;
    tracked: boolean;
    open: number;
    stuck: number;
  }>;
  by_manager: Array<{ manager_id: number; name: string | null; open: number; stuck: number; share: number | null }>;
  work_calendar: { hours: string; workdays: number[] };
  computed_at: string;
}

export interface SecondsStats {
  median_seconds: number | null;
  avg_seconds: number | null;
  count: number;
}

export interface ReactionGroup {
  deals: number;
  take: SecondsStats;
  contact: SecondsStats;
  late: number;
  late_share: number | null;
  waiting: number;
  waiting_late: number;
}

export interface ReactionResponse {
  period_start: string;
  period_end: string;
  summary: ReactionGroup;
  managers: Array<ReactionGroup & { manager_id: number; name: string | null }>;
  worst: Array<{
    deal_id: number;
    bitrix_id: number;
    title: string;
    manager: string | null;
    created_at: string;
    take_seconds: number | null;
    contact_seconds: number | null;
    waiting_seconds: number | null;
    contact_norm_seconds: number | null;
    late: boolean;
    stage: string | null;
    bitrix_url: string | null;
  }>;
  norms: Record<string, { take: number; contact: number; stages: string[] }>;
  skipped_without_history: number;
  definitions: Record<string, string>;
}

export interface OverdueItem {
  activity_id: number;
  bitrix_id: number;
  type: string;
  subject: string | null;
  deadline: string;
  is_open: boolean;
  completed_at: string | null;
  overdue_seconds: number;
  deal_id: number;
  deal_bitrix_id: number;
  deal_title: string;
  manager_id: number | null;
  manager: string | null;
  pipeline: string | null;
  stage: string | null;
  bitrix_url: string | null;
}

export interface OverdueReport {
  date_from: string;
  date_to: string;
  summary: {
    total: number;
    open: number;
    closed_late: number;
    close_delay_median_seconds: number | null;
    close_delay_avg_seconds: number | null;
    unknown_completion: number;
  };
  items: OverdueItem[];
  total: number;
  offset: number;
  limit: number;
}

export type ReportKind = "daily" | "weekly" | "monthly";

export interface ReportBrief {
  id: number;
  kind: ReportKind;
  title: string | null;
  period_start: string;
  period_end: string;
  generated_at: string | null;
  sent_at: string | null;
  sent_to: number;
  send_error: string | null;
  headline: { new?: number; won?: number; lost?: number; overdue?: number; stuck_now?: number };
}

export interface ReportArchive {
  items: ReportBrief[];
  schedule: {
    enabled: boolean;
    daily_time: string;
    weekly_day: string;
    weekly_time: string;
    telegram_configured: boolean;
    recipients: number;
  };
}

interface ReportMetrics {
  new: number;
  won: number;
  won_sum: number;
  lost: number;
  overdue: number;
  reaction_median_seconds: number | null;
  reaction_late_share: number | null;
}

export interface ReportDetail extends ReportBrief {
  text: string;
  data: {
    title: string;
    metrics: ReportMetrics & { overdue_open_now: number; overdue_closed_late: number; stuck_now: number; open_now: number; no_next_activity_now: number };
    previous: ReportMetrics & { period_start: string; period_end: string };
    plan: TargetProgress | null;
    managers: Array<{
      manager_id: number;
      name: string;
      new: number;
      won: number;
      lost: number;
      active: number;
      overdue: number;
      overdue_open: number;
      overdue_share: number | null;
      stuck: number;
      stuck_share: number | null;
      reaction_median_seconds: number | null;
      plan_percent: number | null;
    }>;
    problem_deals: Array<{ deal_id: number; bitrix_id: number; title: string; manager: string | null; stage: string; rule: string; in_stage_seconds: number; unit: SlaUnit; bitrix_url: string | null }>;
    card_quality: {
      no_next_activity: number;
      checked?: number;
      with_issues?: number;
      share?: number | null;
      by_check?: Array<{ code: string; label: string; count: number }>;
      deals: Array<{ deal_id: number; bitrix_id: number; title: string; opportunity: number | null; bitrix_url: string | null }>;
    };
    problem_stages: Array<{ name: string; pipeline: string; rule: string; open: number; stuck: number; overdue: number }>;
    data_warning: string | null;
  };
}

export interface ReportSendResult {
  status: "sent" | "failed" | "skipped";
  reason?: string;
  sent_to?: number;
  errors?: string[];
}

export interface QualityIssue {
  code: string;
  label: string;
}

export interface QualityResponse {
  checked: number;
  with_issues: number;
  share: number | null;
  by_check: Array<QualityIssue & { count: number }>;
  by_manager: Array<{ manager_id: number; name: string | null; checked: number; with_issues: number; issues: number; share: number | null }>;
  items: Array<{
    deal_id: number;
    bitrix_id: number;
    title: string;
    manager: string | null;
    stage: string;
    pipeline: string;
    opportunity: number | null;
    issues: QualityIssue[];
    last_comment: { at: string; text: string } | null;
    bitrix_url: string | null;
  }>;
  total: number;
  notes: string[];
}

export interface QualityRule {
  stage_bitrix_id: string;
  stage_name: string;
  pipeline_name: string;
  category_id: number;
  checks: string[];
  check_labels: Record<string, string>;
  source: "default" | "custom";
}

export interface QualityRulesResponse {
  items: QualityRule[];
  checks: Record<string, string>;
  fields: Array<{ code: string; label: string }>;
}

export interface AvitoStatus {
  configured: boolean;
  config_error: string | null;
  accounts: Array<{ id: number; name: string; last_sync_at: string | null; last_error: string | null }>;
  last_run: { status: string; started_at: string; error: string | null } | null;
  reply_norm_minutes: number;
}

export interface AvitoChatRow {
  chat_id: string;
  account_id: number;
  account: string;
  client_name: string | null;
  item_id: number | null;
  item_title: string | null;
  item_url: string | null;
  first_in_at: string | null;
  first_reply_at: string | null;
  last_message_at: string | null;
  last_direction: string | null;
  messages_count: number;
  reply_seconds: number | null;
  waiting_seconds: number | null;
  late: boolean;
  chat_url: string;
  deal: { deal_id: number; bitrix_id: number; title: string; stage: string | null; won: boolean; lost: boolean; bitrix_url: string | null } | null;
}

export interface AvitoStats {
  new: number;
  replied: number;
  reply_median_seconds: number | null;
  reply_avg_seconds: number | null;
  late: number;
  late_share: number | null;
  no_reply: number;
  linked: number;
  linked_share: number | null;
  won: number;
  lost: number;
}

export interface AvitoSummary {
  period_start: string;
  period_end: string;
  norm_seconds: number;
  summary: AvitoStats & { unanswered_now: number; unanswered_late: number };
  by_account: Array<AvitoStats & { account_id: number; name: string; unanswered_now: number }>;
  by_item: Array<AvitoStats & { item_id: number | null; title: string; url: string | null; account: string }>;
  unanswered: AvitoChatRow[];
  slowest: AvitoChatRow[];
  definitions: Record<string, string>;
}

export interface AvitoConversation {
  chat_id: string;
  account: string;
  client_name: string | null;
  item_title: string | null;
  item_url: string | null;
  chat_url: string;
  deal_bitrix_id: number | null;
  messages: Array<{ id: string; direction: "in" | "out"; created: string; text: string; is_system: boolean }>;
}

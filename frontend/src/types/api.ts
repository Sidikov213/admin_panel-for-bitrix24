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

import { getCookie } from "@/lib/utils";
import type {
  DashboardResponse,
  DealDetail,
  DealListResponse,
  ManagerDetail,
  ManagerListItem,
  OverdueResponse,
  Pipeline,
  PipelineAnalyticsResponse,
  ReportsResponse,
  SalesTarget,
  StalledResponse,
  StalledRulesResponse,
  ManagerControlDetail,
  ManagerControlListResponse,
  ManagerControlMonthReport,
  ManagerControlTeamReport,
  ManagerControlWeekReport,
  McCalendarOverride,
  McControlPolicy,
  McScheduleAssignment,
  McSchedulePreview,
  McWorkSchedule,
  SystemStatus,
  User,
} from "@/types/api";

/** Relative `/api/v1` when Next.js rewrites proxy to backend. */
export function getApiBase(): string {
  const env = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "");
  if (env) return `${env}/api/v1`;
  return "/api/v1";
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  params?: Record<string, string | number | boolean | undefined | null>;
};

function buildUrl(path: string, params?: RequestOptions["params"]): string {
  const base = getApiBase();
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const url = new URL(
    `${base}${normalized}`,
    typeof window !== "undefined" ? window.location.origin : "http://localhost:3000",
  );
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.pathname + url.search;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, params, headers, method = "GET", ...rest } = options;
  const initHeaders = new Headers(headers);
  if (body !== undefined) {
    initHeaders.set("Content-Type", "application/json");
  }
  const mutating = method !== "GET" && method !== "HEAD";
  if (mutating && typeof document !== "undefined") {
    const csrf = getCookie("focus_csrf");
    if (csrf) initHeaders.set("X-CSRF-Token", csrf);
  }

  const res = await fetch(buildUrl(path, params), {
    ...rest,
    method,
    credentials: "include",
    headers: initHeaders,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 204) {
    return undefined as T;
  }

  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!res.ok) {
    const detail =
      typeof data === "object" && data && "detail" in data ? (data as { detail: unknown }).detail : data;
    throw new ApiError(res.statusText || "Request failed", res.status, detail);
  }

  return data as T;
}

export type PeriodParams = {
  period_start?: string;
  period_end?: string;
  preset?: string;
  pipeline_id?: number;
  manager_id?: number;
};

export const api = {
  login: (email: string, password: string) =>
    request<User>("/auth/login", { method: "POST", body: { email, password } }),

  logout: () => request<void>("/auth/logout", { method: "POST" }),

  me: () => request<User>("/auth/me"),

  dashboard: (params?: PeriodParams) => request<DashboardResponse>("/dashboard", { params }),

  reports: (params: PeriodParams) => request<ReportsResponse>("/reports", { params }),

  deals: (params: Record<string, string | number | boolean | undefined | null>) =>
    request<DealListResponse>("/deals", { params }),

  deal: (id: number) => request<DealDetail>(`/deals/${id}`),

  managers: (params?: PeriodParams) => request<ManagerListItem[]>("/managers", { params }),

  manager: (id: number, params?: PeriodParams) =>
    request<ManagerDetail>(`/managers/${id}`, { params }),

  managerDeals: (
    id: number,
    metric: string,
    params?: PeriodParams & { limit?: number },
  ) =>
    request<{ items: Array<Record<string, unknown>>; total: number; metric: string }>(
      `/managers/${id}/deals`,
      { params: { metric, ...params } },
    ),

  pipelines: (params?: PeriodParams & { analytics?: boolean }) =>
    request<PipelineAnalyticsResponse | Pipeline[]>("/pipelines", {
      params: { analytics: params?.analytics ?? true, ...params },
    }),

  overdue: (params?: Record<string, string | number | boolean | undefined | null>) =>
    request<OverdueResponse>("/overdue", { params }),

  stalled: (mode: "no_future" | "rules" = "no_future", params?: PeriodParams) =>
    request<StalledResponse>("/stalled", { params: { mode, ...params } }),

  stalledRules: () => request<StalledRulesResponse>("/stalled-rules"),

  salesRules: () => request<{ items: SalesRule[]; total: number; comments_note?: string }>("/sales-rules"),

  salesRule: (id: number) => request<SalesRule>(`/sales-rules/${id}`),

  createSalesRule: (body: Partial<SalesRule>) =>
    request<SalesRule>("/sales-rules", { method: "POST", body }),

  updateSalesRule: (id: number, body: Partial<SalesRule>) =>
    request<SalesRule>(`/sales-rules/${id}`, { method: "PATCH", body }),

  deleteSalesRule: (id: number) =>
    request<void>(`/sales-rules/${id}`, { method: "DELETE" }),

  previewSalesRule: (body: Partial<SalesRule>) =>
    request<SalesRulePreview>("/sales-rules/preview", { method: "POST", body }),

  evaluateSalesRules: () =>
    request<Record<string, unknown>>("/sales-rules/evaluate", { method: "POST" }),

  dealFields: () =>
    request<{ items: Array<{ field_name: string; title: string; type?: string; is_user_field?: boolean }> }>(
      "/sales-rules/deal-fields",
    ),

  syncDealFields: () =>
    request<{ ok: boolean; count?: number }>("/sales-rules/deal-fields/sync", { method: "POST" }),

  system: () => request<SystemStatus>("/system"),

  targets: () => request<SalesTarget[]>("/targets"),

  managerControl: () => request<ManagerControlListResponse>("/manager-control"),

  managerControlDetail: (id: number) =>
    request<ManagerControlDetail>(`/manager-control/${id}`),

  managerControlWeek: (id: number, params?: { anchor?: string }) =>
    request<ManagerControlWeekReport>(`/manager-control/${id}/week`, { params }),

  managerControlMonth: (id: number, params?: { year?: number; month?: number }) =>
    request<ManagerControlMonthReport>(`/manager-control/${id}/month`, { params }),

  managerControlReport: (params?: {
    period?: "week" | "month";
    start?: string;
    end?: string;
  }) => request<ManagerControlTeamReport>("/manager-control/report", { params }),

  managerControlReportCsvUrl: (params?: { start?: string; end?: string }) =>
    buildUrl("/manager-control/report.csv", params),

  mcAdminSchedules: () =>
    request<{ items: McWorkSchedule[]; total: number }>("/manager-control/admin/schedules"),

  mcAdminCreateSchedule: (body: McWorkSchedule) =>
    request<McWorkSchedule>("/manager-control/admin/schedules", { method: "POST", body }),

  mcAdminUpdateSchedule: (id: number, body: McWorkSchedule) =>
    request<McWorkSchedule>(`/manager-control/admin/schedules/${id}`, { method: "PATCH", body }),

  mcAdminDeleteSchedule: (id: number) =>
    request<{ ok: boolean }>(`/manager-control/admin/schedules/${id}`, { method: "DELETE" }),

  mcAdminAssignments: () =>
    request<{ items: McScheduleAssignment[]; total: number }>("/manager-control/admin/assignments"),

  mcAdminCreateAssignment: (body: {
    schedule_id: number;
    manager_id?: number | null;
    department_key?: string | null;
    note?: string | null;
  }) => request<McScheduleAssignment>("/manager-control/admin/assignments", { method: "POST", body }),

  mcAdminDeleteAssignment: (id: number) =>
    request<{ ok: boolean }>(`/manager-control/admin/assignments/${id}`, { method: "DELETE" }),

  mcAdminCalendar: (params?: { start?: string; end?: string }) =>
    request<{ items: McCalendarOverride[]; total: number }>("/manager-control/admin/calendar", {
      params,
    }),

  mcAdminUpsertCalendar: (body: {
    day_date: string;
    kind: string;
    manager_id?: number | null;
    start_time?: string | null;
    end_time?: string | null;
    required_minutes?: number | null;
    label?: string | null;
    note?: string | null;
  }) => request<{ id: number; day_date: string; kind: string }>("/manager-control/admin/calendar", {
    method: "POST",
    body,
  }),

  mcAdminDeleteCalendar: (id: number) =>
    request<{ ok: boolean }>(`/manager-control/admin/calendar/${id}`, { method: "DELETE" }),

  mcAdminPolicy: () => request<McControlPolicy>("/manager-control/admin/policy"),

  mcAdminPatchPolicy: (body: Partial<McControlPolicy>) =>
    request<McControlPolicy>("/manager-control/admin/policy", { method: "PATCH", body }),

  mcAdminPreview: (params: { schedule_id: number; manager_id: number; days?: number }) =>
    request<McSchedulePreview>("/manager-control/admin/preview", { params }),
};

export type SalesRule = {
  id?: number;
  rule_name: string;
  description?: string | null;
  pipeline_bitrix_id?: number | null;
  stage_id?: number | null;
  pipeline_name?: string | null;
  stage_name?: string | null;
  enabled: boolean;
  max_idle_minutes?: number | null;
  future_activity_required?: boolean | null;
  max_next_activity_minutes?: number | null;
  overdue_activity_allowed?: boolean | null;
  required_fields?: string[] | null;
  required_comment?: boolean | null;
  comment_max_age_minutes?: number | null;
  max_stage_duration_minutes?: number | null;
  severity: string;
  human_description?: string;
  comments_capability?: string;
};

export type SalesRulePreview = {
  deals_affected: number;
  amount_affected: number;
  by_manager: Array<{ manager_id: number | null; manager_name: string; deals_count: number; amount: number }>;
  persisted: boolean;
  human_description?: string;
  note?: string;
};

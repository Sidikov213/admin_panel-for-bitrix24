import { getCookie } from "@/lib/utils";
import type {
  DashboardResponse,
  DealDetail,
  DealListResponse,
  ManagerDetail,
  ManagerListItem,
  OverdueResponse,
  Pipeline,
  ReportsResponse,
  SalesTarget,
  StalledResponse,
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
  const url = new URL(`${base}${normalized}`, typeof window !== "undefined" ? window.location.origin : "http://localhost:3000");
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
    const detail = typeof data === "object" && data && "detail" in data ? (data as { detail: unknown }).detail : data;
    throw new ApiError(res.statusText || "Request failed", res.status, detail);
  }

  return data as T;
}

export const api = {
  login: (email: string, password: string) =>
    request<User>("/auth/login", { method: "POST", body: { email, password } }),

  logout: () => request<void>("/auth/logout", { method: "POST" }),

  me: () => request<User>("/auth/me"),

  dashboard: (params?: {
    period_start?: string;
    period_end?: string;
    pipeline_id?: number;
    manager_id?: number;
  }) => request<DashboardResponse>("/dashboard", { params }),

  reports: (period_start: string, period_end: string, pipeline_id?: number, manager_id?: number) =>
    request<ReportsResponse>("/reports", {
      params: { period_start, period_end, pipeline_id, manager_id },
    }),

  deals: (params: Record<string, string | number | boolean | undefined | null>) =>
    request<DealListResponse>("/deals", { params }),

  deal: (id: number) => request<DealDetail>(`/deals/${id}`),

  managers: () => request<ManagerListItem[]>("/managers"),

  manager: (id: number, period_start?: string, period_end?: string) =>
    request<ManagerDetail>(`/managers/${id}`, { params: { period_start, period_end } }),

  pipelines: () => request<Pipeline[]>("/pipelines"),

  overdue: () => request<OverdueResponse>("/overdue"),

  stalled: (mode: "no_future" | "rules" = "no_future") =>
    request<StalledResponse>("/stalled", { params: { mode } }),

  system: () => request<SystemStatus>("/system"),

  targets: () => request<SalesTarget[]>("/targets"),
};

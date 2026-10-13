"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type PeriodParams } from "@/lib/api";

export function useDashboard(params: PeriodParams) {
  return useQuery({
    queryKey: ["dashboard", params],
    queryFn: () => api.dashboard(params),
  });
}

export function useSystem() {
  return useQuery({ queryKey: ["system"], queryFn: () => api.system() });
}

export function usePipelines(params?: PeriodParams & { analytics?: boolean }) {
  return useQuery({
    queryKey: ["pipelines", params],
    queryFn: () => api.pipelines(params),
  });
}

export function useManagers(params?: PeriodParams) {
  return useQuery({
    queryKey: ["managers", params],
    queryFn: () => api.managers(params),
  });
}

export function useManager(id: number, params?: PeriodParams) {
  return useQuery({
    queryKey: ["managers", id, params],
    queryFn: () => api.manager(id, params),
    enabled: id > 0,
  });
}

export function useDeal(id: number) {
  return useQuery({ queryKey: ["deals", id], queryFn: () => api.deal(id), enabled: id > 0 });
}

export function useOverdue(params?: Record<string, string | number | boolean | undefined | null>) {
  return useQuery({ queryKey: ["overdue", params], queryFn: () => api.overdue(params) });
}

export function useStalled(mode: "no_future" | "rules" = "no_future") {
  return useQuery({ queryKey: ["stalled", mode], queryFn: () => api.stalled(mode) });
}

export function useStalledRules() {
  return useQuery({ queryKey: ["stalled-rules"], queryFn: () => api.stalledRules() });
}

export function useTargets() {
  return useQuery({ queryKey: ["targets"], queryFn: () => api.targets() });
}

export function useReports(params: PeriodParams, enabled = true) {
  return useQuery({
    queryKey: ["reports", params],
    queryFn: () => api.reports(params),
    enabled,
  });
}

export function useManagerControl() {
  return useQuery({
    queryKey: ["manager-control"],
    queryFn: () => api.managerControl(),
    refetchInterval: 60_000,
  });
}

export function useManagerControlDetail(id: number) {
  return useQuery({
    queryKey: ["manager-control", id],
    queryFn: () => api.managerControlDetail(id),
    enabled: id > 0,
    refetchInterval: 60_000,
  });
}

export function useManagerControlWeek(id: number, anchor?: string) {
  return useQuery({
    queryKey: ["manager-control", id, "week", anchor ?? ""],
    queryFn: () => api.managerControlWeek(id, anchor ? { anchor } : undefined),
    enabled: id > 0,
  });
}

export function useManagerControlMonth(id: number, year?: number, month?: number) {
  return useQuery({
    queryKey: ["manager-control", id, "month", year ?? "", month ?? ""],
    queryFn: () => api.managerControlMonth(id, { year, month }),
    enabled: id > 0,
  });
}

export function useManagerControlReport(params?: {
  period?: "week" | "month";
  start?: string;
  end?: string;
}) {
  return useQuery({
    queryKey: ["manager-control", "report", params?.period ?? "week", params?.start ?? "", params?.end ?? ""],
    queryFn: () => api.managerControlReport(params),
  });
}

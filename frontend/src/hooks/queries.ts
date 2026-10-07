"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useDashboard(period_start?: string, period_end?: string) {
  return useQuery({
    queryKey: ["dashboard", period_start, period_end],
    queryFn: () => api.dashboard({ period_start, period_end }),
  });
}

export function useSystem() {
  return useQuery({ queryKey: ["system"], queryFn: () => api.system() });
}

export function usePipelines() {
  return useQuery({ queryKey: ["pipelines"], queryFn: () => api.pipelines() });
}

export function useManagers() {
  return useQuery({ queryKey: ["managers"], queryFn: () => api.managers() });
}

export function useManager(id: number, period_start?: string, period_end?: string) {
  return useQuery({
    queryKey: ["managers", id, period_start, period_end],
    queryFn: () => api.manager(id, period_start, period_end),
    enabled: id > 0,
  });
}

export function useDeal(id: number) {
  return useQuery({ queryKey: ["deals", id], queryFn: () => api.deal(id), enabled: id > 0 });
}

export function useOverdue() {
  return useQuery({ queryKey: ["overdue"], queryFn: () => api.overdue() });
}

export function useStalled(mode: "no_future" | "rules" = "no_future") {
  return useQuery({ queryKey: ["stalled", mode], queryFn: () => api.stalled(mode) });
}

export function useTargets() {
  return useQuery({ queryKey: ["targets"], queryFn: () => api.targets() });
}

export function useReports(period_start: string, period_end: string, enabled = true) {
  return useQuery({
    queryKey: ["reports", period_start, period_end],
    queryFn: () => api.reports(period_start, period_end),
    enabled: enabled && !!period_start && !!period_end,
  });
}

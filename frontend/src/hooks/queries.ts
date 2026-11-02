"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { SalesTargetInput } from "@/types/api";

export function useFunnel(params: { category_id?: number; period_start: string; period_end: string; manager_id?: number }) {
  return useQuery({
    queryKey: ["funnel", params],
    queryFn: () => api.funnel(params),
    enabled: !!params.period_start && !!params.period_end,
    placeholderData: (prev) => prev,
  });
}

export function useTargetsProgress(activeOnly = true, managerId?: number) {
  return useQuery({
    queryKey: ["targets", "progress", activeOnly, managerId ?? null],
    queryFn: () => api.targetsProgress({ active_only: activeOnly, manager_id: managerId }),
  });
}

export function useTargetMutations() {
  const queryClient = useQueryClient();
  const onSuccess = () => void queryClient.invalidateQueries({ queryKey: ["targets"] });
  return {
    create: useMutation({ mutationFn: (body: SalesTargetInput) => api.createTarget(body), onSuccess }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: Partial<SalesTargetInput> }) => api.updateTarget(id, body),
      onSuccess,
    }),
    remove: useMutation({ mutationFn: (id: number) => api.deleteTarget(id), onSuccess }),
  };
}

export function useNotificationStatus() {
  return useQuery({ queryKey: ["notifications", "status"], queryFn: () => api.notificationStatus() });
}

export function useDigestPreview(enabled: boolean) {
  return useQuery({
    queryKey: ["notifications", "preview"],
    queryFn: () => api.digestPreview(),
    enabled,
    staleTime: 0,
  });
}

export function useSendDigest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.sendDigest(),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["notifications", "status"] }),
  });
}

export function useUpdateManagerChat(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (telegram_chat_id: string | null) => api.updateManager(id, { telegram_chat_id }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["managers", id] });
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

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

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ReportKind, SalesTargetInput, SlaUnit } from "@/types/api";

export function useAiStatus() {
  return useQuery({ queryKey: ["ai", "status"], queryFn: () => api.aiStatus() });
}

export function useAiAnalyses(kind?: ReportKind) {
  return useQuery({ queryKey: ["ai", "list", kind ?? "all"], queryFn: () => api.aiAnalyses(kind) });
}

export function useAiAnalysis(id: number | null) {
  return useQuery({ queryKey: ["ai", "detail", id], queryFn: () => api.aiAnalysis(id as number), enabled: id !== null });
}

export function useRunAiAnalysis() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.runAiAnalysis,
    onSuccess: (row) => {
      queryClient.setQueryData(["ai", "detail", row.id], row);
      void queryClient.invalidateQueries({ queryKey: ["ai", "list"] });
      void queryClient.invalidateQueries({ queryKey: ["ai", "status"] });
    },
    onError: () => void queryClient.invalidateQueries({ queryKey: ["ai"] }),
  });
}

export function useAvitoStatus() {
  return useQuery({ queryKey: ["avito", "status"], queryFn: () => api.avitoStatus() });
}

export function useAvitoSummary(params: { period_start?: string; period_end?: string; account_id?: number }) {
  return useQuery({ queryKey: ["avito", "summary", params], queryFn: () => api.avitoSummary(params), placeholderData: (prev) => prev });
}

export function useAvitoChat(chatId: string | null) {
  return useQuery({ queryKey: ["avito", "chat", chatId], queryFn: () => api.avitoChat(chatId as string), enabled: chatId !== null });
}

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

export function useDashboard(params: {
  period_start?: string;
  period_end?: string;
  pipeline_id?: number;
  manager_id?: number;
}) {
  return useQuery({
    queryKey: ["dashboard", params],
    queryFn: () => api.dashboard(params),
    // Keep the previous numbers on screen while a new filter loads
    placeholderData: (prev) => prev,
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

export function useOverdue(params: Record<string, string | number | boolean | undefined>) {
  return useQuery({ queryKey: ["overdue", params], queryFn: () => api.overdue(params), placeholderData: (prev) => prev });
}

export function useStuck(params: { category_id?: number; manager_id?: number; only_stuck?: boolean }) {
  return useQuery({ queryKey: ["sla", "stuck", params], queryFn: () => api.stuck(params), placeholderData: (prev) => prev });
}

export function useReaction(params: { period_start?: string; period_end?: string; category_id?: number; manager_id?: number }) {
  return useQuery({
    queryKey: ["sla", "reaction", params],
    queryFn: () => api.reaction(params),
    placeholderData: (prev) => prev,
  });
}

export function useReportArchive(kind?: ReportKind) {
  return useQuery({ queryKey: ["reportArchive", kind ?? "all"], queryFn: () => api.reportArchive(kind) });
}

export function useReportDetail(id: number | null) {
  return useQuery({ queryKey: ["reportArchive", "detail", id], queryFn: () => api.reportDetail(id as number), enabled: id !== null });
}

export function useReportMutations() {
  const queryClient = useQueryClient();
  const onSuccess = () => void queryClient.invalidateQueries({ queryKey: ["reportArchive"] });
  return {
    generate: useMutation({ mutationFn: ({ kind, day }: { kind: ReportKind; day?: string }) => api.generateReport(kind, day), onSuccess }),
    send: useMutation({ mutationFn: (id: number) => api.sendReport(id), onSuccess }),
  };
}

export function useQuality(params: { category_id?: number; manager_id?: number; check?: string }) {
  return useQuery({ queryKey: ["quality", params], queryFn: () => api.quality(params), placeholderData: (prev) => prev });
}

export function useQualityRules() {
  return useQuery({ queryKey: ["quality", "rules"], queryFn: () => api.qualityRules() });
}

export function useQualityRuleMutations() {
  const queryClient = useQueryClient();
  const onSuccess = () => void queryClient.invalidateQueries({ queryKey: ["quality"] });
  return {
    save: useMutation({ mutationFn: ({ stageId, checks }: { stageId: string; checks: string[] }) => api.putQualityRule(stageId, checks), onSuccess }),
    reset: useMutation({ mutationFn: (stageId: string) => api.resetQualityRule(stageId), onSuccess }),
  };
}

export function useSlaRules() {
  return useQuery({ queryKey: ["sla", "rules"], queryFn: () => api.slaRules() });
}

export function useSlaRuleMutations() {
  const queryClient = useQueryClient();
  const onSuccess = () => void queryClient.invalidateQueries({ queryKey: ["sla"] });
  return {
    save: useMutation({
      mutationFn: ({ stageId, body }: { stageId: string; body: { threshold: number | null; unit: SlaUnit; reaction_stage: boolean } }) =>
        api.putSlaRule(stageId, body),
      onSuccess,
    }),
    reset: useMutation({ mutationFn: (stageId: string) => api.resetSlaRule(stageId), onSuccess }),
  };
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

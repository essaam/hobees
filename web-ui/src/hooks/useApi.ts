import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type {
  ApprovalResolveRequest,
  BeeUpdate,
  ContainerSpec,
  HiveUpdate,
  ProviderModelTestRequest,
  ProviderUpdate,
  ReplayRequest,
} from '../types';

export function useStatus() {
  return useQuery({
    queryKey: ['status'],
    queryFn: api.getStatus,
    refetchInterval: 30000,
  });
}

export function useContainers() {
  return useQuery({
    queryKey: ['containers'],
    queryFn: api.getContainers,
    refetchInterval: 15000,
  });
}

export function useContainerPlan() {
  return useQuery({
    queryKey: ['containers', 'plan'],
    queryFn: api.getContainerPlan,
  });
}

export function useBuildContainerPlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ContainerSpec) => api.buildContainerPlan(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['containers', 'plan'] }),
  });
}

export function useSaveContainerFiles() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { compose: string; dockerfile: string }) => api.saveContainerFiles(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['containers', 'plan'] }),
  });
}

export function useRunContainerAction() {
  return useMutation({
    mutationFn: (body: { action: string; service?: string; detach?: boolean; tail?: number }) =>
      api.runContainerAction(body),
  });
}

export function useProviders() {
  return useQuery({ queryKey: ['providers'], queryFn: api.getProviders });
}

export function useCreateProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createProvider,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['providers'] }),
  });
}

export function useUpdateProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ alias, update }: { alias: string; update: ProviderUpdate }) =>
      api.updateProvider(alias, update),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['providers'] }),
  });
}

export function useDeleteProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteProvider,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['providers'] }),
  });
}

export function useDetectProviderModels() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: {
      alias?: string;
      provider_type?: string;
      base_url?: string;
      api_key_env?: string;
      refresh?: boolean;
    }) => api.detectModels(params),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['providers'] }),
  });
}

export function useTestProviderModel() {
  return useMutation({ mutationFn: (body: ProviderModelTestRequest) => api.testModel(body) });
}

export function useBees() {
  return useQuery({ queryKey: ['bees'], queryFn: api.getBees });
}

export function useCreateBee() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createBee,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['bees'] }),
  });
}

export function useUpdateBee() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, update }: { name: string; update: BeeUpdate }) =>
      api.updateBee(name, update),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['bees'] }),
  });
}

export function useDeleteBee() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteBee,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bees'] });
      qc.invalidateQueries({ queryKey: ['hives'] });
    },
  });
}

export function useHives() {
  return useQuery({ queryKey: ['hives'], queryFn: api.getHives });
}

export function useCreateHive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createHive,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['hives'] }),
  });
}

export function useUpdateHive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, update }: { name: string; update: HiveUpdate }) =>
      api.updateHive(name, update),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['hives'] }),
  });
}

export function useDeleteHive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteHive,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['hives'] }),
  });
}

export function useTools() {
  return useQuery({ queryKey: ['tools'], queryFn: api.getTools });
}

export function useSkills() {
  return useQuery({ queryKey: ['skills'], queryFn: api.getSkills });
}

export function useSaveLastSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.saveLastSkill,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['skills'] }),
  });
}

export function useDeleteSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteSkill,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['skills'] }),
  });
}

export function useConfigYaml(enabled = true) {
  return useQuery({
    queryKey: ['config-yaml'],
    queryFn: api.exportConfigYaml,
    enabled,
  });
}

export function useImportConfigYaml() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.importConfigYaml,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['providers'] });
      qc.invalidateQueries({ queryKey: ['bees'] });
      qc.invalidateQueries({ queryKey: ['hives'] });
      qc.invalidateQueries({ queryKey: ['skills'] });
      qc.invalidateQueries({ queryKey: ['memories'] });
      qc.invalidateQueries({ queryKey: ['config-yaml'] });
    },
  });
}

export function useCreateRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createRun,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['traces'] });
      qc.invalidateQueries({ queryKey: ['containers'] });
    },
  });
}

export function useTraces(params: {
  container?: string;
  hive?: string;
  status?: string;
  q?: string;
  limit?: number;
  offset?: number;
}) {
  return useQuery({
    queryKey: ['traces', params],
    queryFn: () => api.getTraces(params),
    refetchInterval: 5000,
  });
}

export function useTrace(threadId: string | undefined) {
  return useQuery({
    queryKey: ['trace', threadId],
    queryFn: () => api.getTrace(threadId!),
    enabled: Boolean(threadId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'running' || status === 'awaiting_approval' ? 3000 : false;
    },
  });
}

export function useReplayTrace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ threadId, request }: { threadId: string; request: ReplayRequest }) =>
      api.replayTrace(threadId, request),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['trace', vars.threadId] });
      qc.invalidateQueries({ queryKey: ['traces'] });
    },
  });
}

export function usePendingApprovals(container?: string) {
  return useQuery({
    queryKey: ['approvals', { status: 'pending', container }],
    queryFn: () => api.getApprovals({ status: 'pending', container }),
    refetchInterval: 3000,
  });
}

export function useResolveApproval() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ approvalId, request }: { approvalId: number; request: ApprovalResolveRequest }) =>
      api.resolveApproval(approvalId, request),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['approvals'] });
      qc.invalidateQueries({ queryKey: ['traces'] });
      qc.invalidateQueries({ queryKey: ['trace', res.thread_id] });
    },
  });
}

export function useMemories(params: { namespace?: string; q?: string }) {
  return useQuery({
    queryKey: ['memories', params],
    queryFn: () => api.getMemories(params),
  });
}

export function useUpsertMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.upsertMemory,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['memories'] }),
  });
}

export function useDeleteMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteMemory,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['memories'] }),
  });
}

export function useArtifacts(hive?: string) {
  return useQuery({
    queryKey: ['artifacts', hive || ''],
    queryFn: () => api.getArtifacts(hive || undefined),
  });
}

export function useResetPlan(params: { include_artifacts: boolean }) {
  return useQuery({
    queryKey: ['reset', 'plan', params.include_artifacts],
    queryFn: () => api.getResetPlan(params),
  });
}

export function useResetSlate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.resetSlate,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reset', 'plan'] }),
  });
}

export function useTemplates() {
  return useQuery({ queryKey: ['templates'], queryFn: api.getTemplates });
}

export function useApplyTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.applyTemplate,
    onSuccess: () => {
      // A template writes providers, bees, hives, skills, memory and the assistant,
      // so every view that reads them has to refresh.
      for (const key of ['templates', 'providers', 'bees', 'hives', 'skills', 'memories']) {
        qc.invalidateQueries({ queryKey: [key] });
      }
    },
  });
}

export function useDetectProviders() {
  return useMutation({ mutationFn: api.detectProviders });
}

export function useRegisterDetectedProviders() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.registerDetectedProviders,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['providers'] }),
  });
}

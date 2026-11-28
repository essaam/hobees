import type {
  ApprovalListResponse,
  ApprovalResolveRequest,
  ApprovalResolveResponse,
  ArtifactListResponse,
  Bee,
  BeeCreate,
  BeeUpdate,
  ConfigYamlResponse,
  ContainerListResponse,
  ContainerPlanResponse,
  ContainerSaveRequest,
  ContainerSaveResponse,
  ContainerSpec,
  Hive,
  HiveCreate,
  HiveUpdate,
  MemoryCreate,
  MemoryListResponse,
  Provider,
  ProviderCreate,
  ProviderDetectionResponse,
  ProviderModelTestRequest,
  ProviderModelTestResponse,
  ProviderModelsResponse,
  ProviderRegisterResponse,
  ProviderUpdate,
  ReplayRequest,
  ReplayResponse,
  ResetPlanResponse,
  ResetRequest,
  ResetResponse,
  RunCreate,
  RunResponse,
  Skill,
  StatusResponse,
  TemplateApplyRequest,
  TemplateApplyResponse,
  TemplateItem,
  ToolsResponse,
  TraceDetail,
  TraceSummary,
} from '../types';

const API_BASE = '/api/v1';

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.body && !(options.headers && 'Content-Type' in (options.headers as Record<string, string>))
      ? { 'Content-Type': 'application/json' }
      : {}),
    ...((options.headers as Record<string, string>) || {}),
  };

  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (data && typeof data === 'object' && 'detail' in data) {
        message = String(data.detail);
      }
    } catch {
      // ignore
    }
    throw new ApiError(res.status, message);
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return res.json();
}

export const api = {
  getStatus: () => request<StatusResponse>('/status'),
  getContainers: () => request<ContainerListResponse>('/containers'),
  getContainerPlan: () => request<ContainerPlanResponse>('/containers/plan'),
  buildContainerPlan: (body: ContainerSpec) =>
    request<ContainerPlanResponse>('/containers/plan', { method: 'POST', body: JSON.stringify(body) }),
  saveContainerFiles: (body: ContainerSaveRequest) =>
    request<ContainerSaveResponse>('/containers/files', { method: 'POST', body: JSON.stringify(body) }),

  getProviders: () => request<Provider[]>('/providers'),
  createProvider: (body: ProviderCreate) =>
    request<Provider>('/providers', { method: 'POST', body: JSON.stringify(body) }),
  updateProvider: (alias: string, body: ProviderUpdate) =>
    request<Provider>(`/providers/${encodeURIComponent(alias)}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  deleteProvider: (alias: string) =>
    request<{ success: boolean }>(`/providers/${encodeURIComponent(alias)}`, {
      method: 'DELETE',
    }),

  detectModels: (params: {
    alias?: string;
    provider_type?: string;
    base_url?: string;
    api_key_env?: string;
    refresh?: boolean;
  }) => {
    const sp = new URLSearchParams();
    if (params.alias) sp.set('alias', params.alias);
    if (params.provider_type) sp.set('provider_type', params.provider_type);
    if (params.base_url) sp.set('base_url', params.base_url);
    if (params.api_key_env) sp.set('api_key_env', params.api_key_env);
    if (params.refresh) sp.set('refresh', 'true');
    const qs = sp.toString();
    return request<ProviderModelsResponse>(`/providers/models${qs ? `?${qs}` : ''}`);
  },

  testModel: (body: ProviderModelTestRequest) =>
    request<ProviderModelTestResponse>('/providers/test', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  detectProviders: () =>
    request<ProviderDetectionResponse>('/providers/detect', { method: 'POST' }),

  registerDetectedProviders: (aliases: string[]) =>
    request<ProviderRegisterResponse>('/providers/detect/register', {
      method: 'POST',
      body: JSON.stringify({ aliases }),
    }),

  getBees: () => request<Bee[]>('/bees'),
  createBee: (body: BeeCreate) =>
    request<Bee>('/bees', { method: 'POST', body: JSON.stringify(body) }),
  updateBee: (name: string, body: BeeUpdate) =>
    request<Bee>(`/bees/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  deleteBee: (name: string) =>
    request<{ success: boolean }>(`/bees/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),

  getHives: () => request<Hive[]>('/hives'),
  createHive: (body: HiveCreate) =>
    request<Hive>('/hives', { method: 'POST', body: JSON.stringify(body) }),
  updateHive: (name: string, body: HiveUpdate) =>
    request<Hive>(`/hives/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  deleteHive: (name: string) =>
    request<{ success: boolean }>(`/hives/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),

  getTools: () => request<ToolsResponse>('/tools'),

  getSkills: () => request<Skill[]>('/skills'),
  saveLastSkill: () => request<Skill>('/skills/save-last', { method: 'POST' }),
  deleteSkill: (name: string) =>
    request<{ success: boolean }>(`/skills/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),

  exportConfigYaml: () => request<ConfigYamlResponse>('/config/yaml'),
  importConfigYaml: (yaml: string) =>
    request<{ success: boolean }>('/config/yaml', {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      body: yaml,
    }),

  getTemplates: () => request<TemplateItem[]>('/templates'),
  applyTemplate: (body: TemplateApplyRequest) =>
    request<TemplateApplyResponse>('/templates/apply', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  createRun: (body: RunCreate) =>
    request<RunResponse>('/runs', { method: 'POST', body: JSON.stringify(body) }),

  getTraces: (params: {
    container?: string;
    hive?: string;
    status?: string;
    q?: string;
    limit?: number;
    offset?: number;
  }) => {
    const sp = new URLSearchParams();
    if (params.container && params.container !== 'all') sp.set('container', params.container);
    if (params.hive) sp.set('hive', params.hive);
    if (params.status && params.status !== 'all') sp.set('status', params.status);
    if (params.q) sp.set('q', params.q);
    if (params.limit) sp.set('limit', String(params.limit));
    if (params.offset) sp.set('offset', String(params.offset));
    const qs = sp.toString();
    return request<TraceSummary[]>(`/traces${qs ? `?${qs}` : ''}`);
  },

  getTrace: (threadId: string) =>
    request<TraceDetail>(`/traces/${encodeURIComponent(threadId)}`),

  replayTrace: (threadId: string, body: ReplayRequest) =>
    request<ReplayResponse>(`/traces/${encodeURIComponent(threadId)}/replay`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  getApprovals: (params: { status?: string; container?: string }) => {
    const sp = new URLSearchParams();
    if (params.status) sp.set('status', params.status);
    if (params.container && params.container !== 'all') sp.set('container', params.container);
    const qs = sp.toString();
    return request<ApprovalListResponse>(`/approvals${qs ? `?${qs}` : ''}`);
  },

  resolveApproval: (approvalId: number, body: ApprovalResolveRequest) =>
    request<ApprovalResolveResponse>(`/approvals/${approvalId}/resolve`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  getMemories: (params: { namespace?: string; q?: string }) => {
    const sp = new URLSearchParams();
    if (params.namespace && params.namespace !== 'all') sp.set('namespace', params.namespace);
    if (params.q) sp.set('q', params.q);
    const qs = sp.toString();
    return request<MemoryListResponse>(`/memories${qs ? `?${qs}` : ''}`);
  },

  upsertMemory: (body: MemoryCreate) =>
    request<{ success: boolean }>('/memories', { method: 'POST', body: JSON.stringify(body) }),

  deleteMemory: (id: number) =>
    request<{ success: boolean }>(`/memories/${id}`, { method: 'DELETE' }),

  getArtifacts: (hive?: string) => {
    const sp = new URLSearchParams();
    if (hive) sp.set('hive', hive);
    const qs = sp.toString();
    return request<ArtifactListResponse>(`/artifacts${qs ? `?${qs}` : ''}`);
  },

  artifactContentUrl: (path: string, hive?: string, download = false) => {
    const sp = new URLSearchParams({ path });
    if (hive) sp.set('hive', hive);
    if (download) sp.set('download', 'true');
    return `${API_BASE}/artifacts/content?${sp.toString()}`;
  },

  fetchArtifactText: async (path: string, hive?: string) => {
    const url = api.artifactContentUrl(path, hive, false);
    const res = await fetch(url);
    if (!res.ok) throw new ApiError(res.status, 'Failed to load artifact');
    return res.text();
  },

  getResetPlan: (params: { include_artifacts: boolean }) => {
    const sp = new URLSearchParams();
    if (params.include_artifacts) sp.set('include_artifacts', 'true');
    const qs = sp.toString();
    return request<ResetPlanResponse>(`/reset/plan${qs ? `?${qs}` : ''}`);
  },

  resetSlate: (body: ResetRequest) =>
    request<ResetResponse>('/reset', { method: 'POST', body: JSON.stringify(body) }),
};

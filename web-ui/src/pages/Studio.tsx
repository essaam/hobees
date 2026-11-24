import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Bot,
  Check,
  Code2,
  Container,
  Copy,
  Download,
  Edit3,
  Key,
  LayoutGrid,
  Loader2,
  Plus,
  Sparkles,
  Trash2,
  Upload,
  Users,
  X,
} from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import {
  useBees,
  useConfigYaml,
  useContainerPlan,
  useContainers,
  useBuildContainerPlan,
  useSaveContainerFiles,
  useRunContainerAction,
  useCreateBee,
  useCreateHive,
  useCreateProvider,
  useDeleteBee,
  useDeleteHive,
  useDeleteProvider,
  useDeleteSkill,
  useDetectProviderModels,
  useHives,
  useImportConfigYaml,
  useProviders,
  useSaveLastSkill,
  useSkills,
  useTestProviderModel,
  useTools,
  useUpdateBee,
  useUpdateHive,
  useUpdateProvider,
} from '../hooks/useApi';
import type { Bee, ContainerSpec, Hive, Provider, ProviderModelTestResponse, ToolSchema } from '../types';
import { cn, copyText, downloadText } from '../utils/helpers';

type StudioTab = 'hives' | 'bees' | 'providers' | 'skills' | 'containers';

export function Studio() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { readOnly } = useAppContext();

  const initialTab = (searchParams.get('tab') as StudioTab) || 'hives';
  const [tab, setTab] = useState<StudioTab>(
    ['hives', 'bees', 'providers', 'skills', 'containers'].includes(initialTab) ? initialTab : 'hives',
  );
  const [viewMode, setViewMode] = useState<'visual' | 'yaml'>(
    searchParams.get('mode') === 'yaml' ? 'yaml' : 'visual',
  );

  const { data: providers = [] } = useProviders();
  const { data: bees = [] } = useBees();
  const { data: hives = [] } = useHives();
  const { data: skills = [] } = useSkills();
  const { data: toolsData } = useTools();
  const tools = toolsData?.tools ?? [];
  const { data: containerList } = useContainers();

  const { data: yamlData, isLoading: yamlLoading, refetch: refetchYaml } = useConfigYaml(
    viewMode === 'yaml',
  );
  const importYaml = useImportConfigYaml();

  const createProvider = useCreateProvider();
  const updateProvider = useUpdateProvider();
  const deleteProvider = useDeleteProvider();

  const createBee = useCreateBee();
  const updateBee = useUpdateBee();
  const deleteBee = useDeleteBee();

  const createHive = useCreateHive();
  const updateHive = useUpdateHive();
  const deleteHive = useDeleteHive();

  const saveLastSkill = useSaveLastSkill();
  const deleteSkill = useDeleteSkill();

  const [editingProvider, setEditingProvider] = useState<Provider | 'new' | null>(null);
  const [editingBee, setEditingBee] = useState<Bee | 'new' | null>(null);
  const [editingHive, setEditingHive] = useState<Hive | 'new' | null>(null);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);

  // Raw YAML editor state
  const [yamlDraft, setYamlDraft] = useState('');
  const [yamlStatus, setYamlStatus] = useState<string | null>(null);
  const [copiedYaml, setCopiedYaml] = useState(false);

  useEffect(() => {
    const t = searchParams.get('tab') as StudioTab | null;
    if (t && ['hives', 'bees', 'providers', 'skills', 'containers'].includes(t)) {
      setTab(t);
    }
    const mode = searchParams.get('mode');
    if (mode === 'yaml') {
      setViewMode('yaml');
    } else if (mode === 'visual') {
      setViewMode('visual');
    }
    if (searchParams.get('create') === '1' && !readOnly) {
      if (t === 'providers') setEditingProvider('new');
      else if (t === 'bees') setEditingBee('new');
      else if (t === 'hives') setEditingHive('new');
      const next = new URLSearchParams(searchParams);
      next.delete('create');
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, readOnly, setSearchParams]);

  useEffect(() => {
    if (yamlData?.yaml !== undefined) {
      setYamlDraft(yamlData.yaml);
    }
  }, [yamlData?.yaml]);

  const handleApplyYaml = async () => {
    setYamlStatus(null);
    try {
      await importYaml.mutateAsync(yamlDraft);
      setYamlStatus('Configuration imported successfully.');
      refetchYaml();
    } catch (err) {
      setYamlStatus(err instanceof Error ? err.message : 'Import failed');
    }
  };

  const handleDelete = async (kind: StudioTab, name: string) => {
    if (!window.confirm(`Delete ${kind.slice(0, -1)} "${name}"?`)) return;
    setErrorBanner(null);
    try {
      if (kind === 'providers') await deleteProvider.mutateAsync(name);
      else if (kind === 'bees') await deleteBee.mutateAsync(name);
      else if (kind === 'hives') await deleteHive.mutateAsync(name);
      else if (kind === 'skills') await deleteSkill.mutateAsync(name);
    } catch (err) {
      setErrorBanner(err instanceof Error ? err.message : 'Delete failed');
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 space-y-5">
      {/* Header + Visual/YAML Toggle */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-zinc-900">Studio</h1>
          <p className="mt-0.5 text-sm text-zinc-500">
            Configure Hives, Worker Bees, tool approval gates, Providers, Skills, and Containers.
          </p>
        </div>

        <div className="inline-flex rounded-lg border border-zinc-200 bg-white p-0.5 text-xs font-medium">
          <button
            type="button"
            onClick={() => setViewMode('visual')}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 transition-colors',
              viewMode === 'visual' ? 'bg-zinc-900 text-white' : 'text-zinc-600 hover:text-zinc-900',
            )}
          >
            <LayoutGrid className="h-3.5 w-3.5" />
            Visual
          </button>
          <button
            type="button"
            onClick={() => setViewMode('yaml')}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 transition-colors',
              viewMode === 'yaml' ? 'bg-zinc-900 text-white' : 'text-zinc-600 hover:text-zinc-900',
            )}
          >
            <Code2 className="h-3.5 w-3.5" />
            Raw YAML
          </button>
        </div>
      </div>

      {errorBanner && (
        <div className="flex items-center justify-between rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-xs text-rose-700">
          <span>{errorBanner}</span>
          <button type="button" onClick={() => setErrorBanner(null)}>
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {viewMode === 'yaml' ? (
        <div className="overflow-hidden rounded-2xl border border-zinc-200/90 bg-white shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-100 px-4 py-3">
            <span className="font-mono text-xs font-medium text-zinc-600">hobees.yaml</span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  copyText(yamlDraft);
                  setCopiedYaml(true);
                  setTimeout(() => setCopiedYaml(false), 1500);
                }}
                className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-2.5 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50"
              >
                {copiedYaml ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
                Copy
              </button>
              <button
                type="button"
                onClick={() => downloadText(yamlDraft, 'hobees.yaml', 'text/yaml')}
                className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-2.5 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50"
              >
                <Download className="h-3.5 w-3.5" />
                Download
              </button>
              {!readOnly && (
                <button
                  type="button"
                  disabled={importYaml.isPending}
                  onClick={handleApplyYaml}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-800 disabled:opacity-50"
                >
                  {importYaml.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Upload className="h-3.5 w-3.5" />
                  )}
                  Apply YAML
                </button>
              )}
            </div>
          </div>

          {yamlStatus && (
            <div className="border-b border-zinc-100 bg-zinc-50 px-4 py-2 text-xs text-zinc-700">
              {yamlStatus}
            </div>
          )}

          {yamlLoading ? (
            <div className="p-12 text-center text-xs text-zinc-400">Loading YAML…</div>
          ) : (
            <textarea
              value={yamlDraft}
              onChange={(e) => setYamlDraft(e.target.value)}
              readOnly={readOnly}
              spellCheck={false}
              rows={24}
              className="w-full resize-y bg-zinc-950 p-4 font-mono text-xs leading-relaxed text-zinc-100 focus:outline-none"
            />
          )}
        </div>
      ) : (
        <>
          {/* Entity Tabs + Create Button */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="inline-flex rounded-lg border border-zinc-200 bg-white p-0.5 text-xs font-medium">
              {(
                [
                  { id: 'hives', label: 'Hives', count: hives.length, icon: Users },
                  { id: 'bees', label: 'Bees', count: bees.length, icon: Bot },
                  { id: 'providers', label: 'Providers', count: providers.length, icon: Key },
                  { id: 'skills', label: 'Skills', count: skills.length, icon: Sparkles },
                  { id: 'containers', label: 'Containers', count: containerList?.containers.length ?? 0, icon: Container },
                ] as const
              ).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setTab(item.id)}
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 transition-colors',
                    tab === item.id ? 'bg-zinc-900 text-white' : 'text-zinc-600 hover:text-zinc-900',
                  )}
                >
                  <item.icon className="h-3.5 w-3.5" />
                  {item.label}
                  <span
                    className={cn(
                      'rounded-full px-1.5 text-[10px]',
                      tab === item.id ? 'bg-white/20 text-white' : 'bg-zinc-100 text-zinc-500',
                    )}
                  >
                    {item.count}
                  </span>
                </button>
              ))}
            </div>

            {!readOnly && (
              <div>
                {tab === 'hives' && (
                  <button
                    type="button"
                    onClick={() => setEditingHive('new')}
                    disabled={providers.length === 0}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-800 disabled:opacity-40"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    New Hive
                  </button>
                )}
                {tab === 'bees' && (
                  <button
                    type="button"
                    onClick={() => setEditingBee('new')}
                    disabled={providers.length === 0}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-800 disabled:opacity-40"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    New Bee
                  </button>
                )}
                {tab === 'providers' && (
                  <button
                    type="button"
                    onClick={() => setEditingProvider('new')}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-800"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    Add Provider
                  </button>
                )}
                {tab === 'skills' && (
                  <button
                    type="button"
                    disabled={saveLastSkill.isPending}
                    onClick={async () => {
                      setErrorBanner(null);
                      try {
                        await saveLastSkill.mutateAsync();
                      } catch (err) {
                        setErrorBanner(err instanceof Error ? err.message : 'Could not harvest skill');
                      }
                    }}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-800 disabled:opacity-40"
                  >
                    <Sparkles className="h-3.5 w-3.5" />
                    Save Last Run as Skill
                  </button>
                )}
              </div>
            )}
          </div>

          {/* List Cards */}
          <div className="space-y-2.5">
            {tab === 'containers' && <ContainersTab readOnly={readOnly} />}
            {tab === 'hives' &&
              (hives.length === 0 ? (
                <EmptyBox text="No Hives yet. Create one to coordinate specialist Worker Bees." />
              ) : (
                hives.map((h) => (
                  <div
                    key={h.id}
                    className="flex items-start justify-between gap-4 rounded-xl border border-zinc-200/90 bg-white p-4 shadow-sm"
                  >
                    <div className="min-w-0 space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-zinc-900">{h.name}</span>
                        {h.is_dynamic && (
                          <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800">
                            dynamic
                          </span>
                        )}
                      </div>
                      {h.goal_description && (
                        <p className="text-xs text-zinc-500 line-clamp-2">{h.goal_description}</p>
                      )}
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 text-xs text-zinc-500">
                        <span className="font-mono">
                          {h.supervisor_provider_alias ?? `#${h.supervisor_provider_id}`}/{h.supervisor_model_name}
                        </span>
                        <span>thinking: {h.supervisor_thinking_level}</span>
                        <span>
                          bees: {h.bee_names.length > 0 ? h.bee_names.join(', ') : 'none'}
                        </span>
                      </div>
                    </div>
                    {!readOnly && (
                      <div className="flex shrink-0 items-center gap-1">
                        <button
                          type="button"
                          onClick={() => setEditingHive(h)}
                          className="rounded-lg p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-800"
                          aria-label={`Edit ${h.name}`}
                        >
                          <Edit3 className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete('hives', h.name)}
                          className="rounded-lg p-1.5 text-zinc-400 hover:bg-rose-50 hover:text-rose-600"
                          aria-label={`Delete ${h.name}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    )}
                  </div>
                ))
              ))}

            {tab === 'bees' &&
              (bees.length === 0 ? (
                <EmptyBox text="No Worker Bees yet. Create a Bee and assign its tools and approval gates." />
              ) : (
                bees.map((b) => (
                  <div
                    key={b.id}
                    className="flex items-start justify-between gap-4 rounded-xl border border-zinc-200/90 bg-white p-4 shadow-sm"
                  >
                    <div className="min-w-0 space-y-1">
                      <span className="text-sm font-semibold text-zinc-900">{b.name}</span>
                      <p className="text-xs text-zinc-500 line-clamp-2">{b.role_description}</p>
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 text-xs text-zinc-500">
                        <span className="font-mono">
                          {b.provider_alias ?? `#${b.provider_id}`}/{b.model_name}
                        </span>
                        <span>thinking: {b.thinking_level}</span>
                        <span>tools: {b.tool_names.length}</span>
                        {b.require_approval.length > 0 && (
                          <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800">
                            gated: {b.require_approval.join(', ')}
                          </span>
                        )}
                      </div>
                    </div>
                    {!readOnly && (
                      <div className="flex shrink-0 items-center gap-1">
                        <button
                          type="button"
                          onClick={() => setEditingBee(b)}
                          className="rounded-lg p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-800"
                          aria-label={`Edit ${b.name}`}
                        >
                          <Edit3 className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete('bees', b.name)}
                          className="rounded-lg p-1.5 text-zinc-400 hover:bg-rose-50 hover:text-rose-600"
                          aria-label={`Delete ${b.name}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    )}
                  </div>
                ))
              ))}

            {tab === 'providers' &&
              (providers.length === 0 ? (
                <EmptyBox text="No LLM Providers registered yet. Add one to start creating Bees and Hives." />
              ) : (
                providers.map((p) => (
                  <div
                    key={p.id}
                    className="flex items-start justify-between gap-4 rounded-xl border border-zinc-200/90 bg-white p-4 shadow-sm"
                  >
                    <div className="min-w-0 space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-zinc-900">{p.alias}</span>
                        <span className="rounded bg-zinc-100 px-2 py-0.5 font-mono text-[11px] text-zinc-600">
                          {p.provider_type}
                        </span>
                      </div>
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-500">
                        <span className="font-mono">{p.default_model ?? 'no default model'}</span>
                        <span>env: <code className="text-zinc-700">{p.api_key_env}</code></span>
                        {p.base_url && <span className="font-mono truncate max-w-xs">{p.base_url}</span>}
                        <span>${p.input_cost_per_1m}/${p.output_cost_per_1m} per 1M</span>
                      </div>
                    </div>
                    {!readOnly && (
                      <div className="flex shrink-0 items-center gap-1">
                        <button
                          type="button"
                          onClick={() => setEditingProvider(p)}
                          className="rounded-lg p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-800"
                          aria-label={`Edit ${p.alias}`}
                        >
                          <Edit3 className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete('providers', p.alias)}
                          className="rounded-lg p-1.5 text-zinc-400 hover:bg-rose-50 hover:text-rose-600"
                          aria-label={`Delete ${p.alias}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    )}
                  </div>
                ))
              ))}

            {tab === 'skills' &&
              (skills.length === 0 ? (
                <EmptyBox text="No saved skills yet. Complete a Hive run and save it as a reusable skill." />
              ) : (
                skills.map((s) => (
                  <div
                    key={s.id}
                    className="flex items-start justify-between gap-4 rounded-xl border border-zinc-200/90 bg-white p-4 shadow-sm"
                  >
                    <div className="min-w-0 space-y-1">
                      <span className="text-sm font-semibold text-zinc-900">{s.name}</span>
                      <p className="text-xs text-zinc-500">{s.description}</p>
                      <div className="flex flex-wrap items-center gap-3 pt-1 text-xs text-zinc-400">
                        <span>used {s.usage_count}×</span>
                        {s.tags.length > 0 && <span>{s.tags.join(', ')}</span>}
                      </div>
                    </div>
                    {!readOnly && (
                      <button
                        type="button"
                        onClick={() => handleDelete('skills', s.name)}
                        className="rounded-lg p-1.5 text-zinc-400 hover:bg-rose-50 hover:text-rose-600"
                        aria-label={`Delete ${s.name}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                ))
              ))}
          </div>
        </>
      )}

      {/* Modals */}
      {editingProvider && (
        <ProviderDialog
          initial={editingProvider === 'new' ? null : editingProvider}
          saving={createProvider.isPending || updateProvider.isPending}
          onClose={() => setEditingProvider(null)}
          onSave={async (payload, isEdit) => {
            if (isEdit) {
              const { alias, ...rest } = payload;
              await updateProvider.mutateAsync({ alias, update: rest });
            } else {
              await createProvider.mutateAsync(payload);
            }
            setEditingProvider(null);
          }}
        />
      )}

      {editingBee && (
        <BeeDialog
          initial={editingBee === 'new' ? null : editingBee}
          providers={providers}
          tools={tools}
          saving={createBee.isPending || updateBee.isPending}
          onClose={() => setEditingBee(null)}
          onSave={async (payload, isEdit) => {
            if (isEdit) {
              const { name, ...rest } = payload;
              await updateBee.mutateAsync({ name, update: rest });
            } else {
              await createBee.mutateAsync(payload);
            }
            setEditingBee(null);
          }}
        />
      )}

      {editingHive && (
        <HiveDialog
          initial={editingHive === 'new' ? null : editingHive}
          providers={providers}
          bees={bees}
          saving={createHive.isPending || updateHive.isPending}
          onClose={() => setEditingHive(null)}
          onSave={async (payload, isEdit) => {
            if (isEdit) {
              const { name, ...rest } = payload;
              await updateHive.mutateAsync({ name, update: rest });
            } else {
              await createHive.mutateAsync(payload);
            }
            setEditingHive(null);
          }}
        />
      )}
    </div>
  );
}

function ContainersTab({ readOnly }: { readOnly: boolean }) {
  const { data: plan, isLoading } = useContainerPlan();
  const buildPlan = useBuildContainerPlan();
  const saveFiles = useSaveContainerFiles();
  const runAction = useRunContainerAction();

  const [fields, setFields] = useState({
    service: 'hobees',
    image: 'hobees:local',
    base_image: 'python:3.12-slim',
    container_name: '',
    profiles: 'runtime_only',
    ports: '8420:8420',
    volumes: './artifacts:/data/artifacts, ./skills:/data/skills',
    command: 'web --host 0.0.0.0 --port 8420',
    include_db: true,
  });
  const [compose, setCompose] = useState('');
  const [dockerfile, setDockerfile] = useState('');
  const [warnings, setWarnings] = useState<string[]>([]);
  const [output, setOutput] = useState('');

  useEffect(() => {
    if (!plan) return;
    setCompose(plan.compose);
    setDockerfile(plan.dockerfile);
    setWarnings(plan.warnings);
    setFields((prev) => ({
      ...prev,
      service: plan.spec.service,
      image: plan.spec.image,
      base_image: plan.spec.base_image,
      container_name: plan.spec.container_name,
      profiles: plan.spec.profiles.join(', '),
      ports: plan.spec.ports.join(', '),
      volumes: plan.spec.volumes.join(', '),
      command: plan.spec.command.join(' '),
      include_db: plan.spec.include_db,
    }));
  }, [plan]);

  const list = (value: string) => value.split(',').map((item) => item.trim()).filter(Boolean);

  const spec = (): ContainerSpec => ({
    project: plan?.spec.project ?? 'hobees',
    service: fields.service,
    image: fields.image,
    container_name: fields.container_name,
    base_image: fields.base_image,
    working_dir: plan?.spec.working_dir ?? '/app',
    user: plan?.spec.user ?? '${HOBEES_UID:-1000}:${HOBEES_GID:-1000}',
    entrypoint: plan?.spec.entrypoint ?? ['hobees'],
    command: list(fields.command),
    profiles: list(fields.profiles),
    restart: plan?.spec.restart ?? 'unless-stopped',
    ports: list(fields.ports),
    volumes: list(fields.volumes),
    env: plan?.spec.env ?? {},
    api_key_envs: plan?.spec.api_key_envs ?? [],
    include_db: fields.include_db,
    db_image: plan?.spec.db_image ?? 'postgres:16-alpine',
    db_volume: plan?.spec.db_volume ?? 'postgres_data',
  });

  const preview = async () => {
    setOutput('');
    try {
      const res = await buildPlan.mutateAsync(spec());
      setCompose(res.compose);
      setDockerfile(res.dockerfile);
      setWarnings(res.warnings);
    } catch (err) {
      setOutput(err instanceof Error ? err.message : 'Preview failed');
    }
  };

  const save = async () => {
    if (readOnly) return;
    try {
      const res = await saveFiles.mutateAsync({ compose, dockerfile });
      setOutput(`Saved ${res.saved.join(', ')}`);
      setWarnings(res.warnings);
    } catch (err) {
      setOutput(err instanceof Error ? err.message : 'Save failed');
    }
  };

  const run = async (action: string) => {
    if (readOnly) return;
    try {
      const res = await runAction.mutateAsync({ action, service: fields.service, detach: action === 'up' });
      setOutput(res.success ? res.output : res.detail || `docker compose ${action} failed`);
    } catch (err) {
      setOutput(err instanceof Error ? err.message : 'Action failed');
    }
  };

  if (isLoading || !plan) return <EmptyBox text="Reading the container plan…" />;

  const canRunContainer = !readOnly && plan.docker_available;
  return (
    <div className="space-y-3 rounded-xl border border-zinc-200/90 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <span className="text-sm font-semibold text-zinc-900">{fields.service}</span>
          <p className="mt-0.5 text-xs text-zinc-500">{plan.project_dir}</p>
        </div>
        <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-medium', plan.docker_available ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700')}>
          {plan.docker_available ? 'docker available' : 'docker is not available on this host'}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Service name">
          <input value={fields.service} onChange={(e) => setFields((prev) => ({ ...prev, service: e.target.value }))} readOnly={readOnly} className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs" />
        </Field>
        <Field label="Image">
          <input value={fields.image} onChange={(e) => setFields((prev) => ({ ...prev, image: e.target.value }))} readOnly={readOnly} className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs" />
        </Field>
        <Field label="Container name">
          <input value={fields.container_name} onChange={(e) => setFields((prev) => ({ ...prev, container_name: e.target.value }))} readOnly={readOnly} className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs" />
        </Field>
        <Field label="Base image">
          <input value={fields.base_image} onChange={(e) => setFields((prev) => ({ ...prev, base_image: e.target.value }))} readOnly={readOnly} className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs" />
        </Field>
        <Field label="Profiles (comma-separated)">
          <input value={fields.profiles} onChange={(e) => setFields((prev) => ({ ...prev, profiles: e.target.value }))} readOnly={readOnly} className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs" />
        </Field>
        <Field label="Ports (comma-separated)">
          <input value={fields.ports} onChange={(e) => setFields((prev) => ({ ...prev, ports: e.target.value }))} readOnly={readOnly} className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs" />
        </Field>
        <Field label="Volumes (host:container, comma-separated)">
          <input value={fields.volumes} onChange={(e) => setFields((prev) => ({ ...prev, volumes: e.target.value }))} readOnly={readOnly} className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs" />
        </Field>
        <Field label="Command">
          <input value={fields.command} onChange={(e) => setFields((prev) => ({ ...prev, command: e.target.value }))} readOnly={readOnly} className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs" />
        </Field>
      </div>

      <label className="flex items-center gap-2 text-xs text-zinc-600">
        <input type="checkbox" checked={fields.include_db} onChange={(e) => setFields((prev) => ({ ...prev, include_db: e.target.checked }))} disabled={readOnly} />
        include a Postgres service ({'environment values stay as ${NAME} references, never literal keys'})
      </label>

      {warnings.length > 0 && (
        <ul className="space-y-1 rounded-lg border border-amber-200 bg-amber-50/60 p-3 text-xs text-amber-800">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Field label="compose.yaml">
          <textarea value={compose} onChange={(e) => setCompose(e.target.value)} readOnly={readOnly} spellCheck={false} rows={14} className="w-full resize-y rounded-lg border border-zinc-200 bg-zinc-950 p-3 font-mono text-xs leading-relaxed text-zinc-100 focus:outline-none" />
        </Field>
        <Field label="Dockerfile">
          <textarea value={dockerfile} onChange={(e) => setDockerfile(e.target.value)} readOnly={readOnly} spellCheck={false} rows={14} className="w-full resize-y rounded-lg border border-zinc-200 bg-zinc-950 p-3 font-mono text-xs leading-relaxed text-zinc-100 focus:outline-none" />
        </Field>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" disabled={buildPlan.isPending} onClick={preview} className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50">
          <Code2 className="h-3.5 w-3.5" />
          Preview spec
        </button>
        <button type="button" disabled={readOnly || saveFiles.isPending} onClick={save} className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-800 disabled:opacity-40">
          <Upload className="h-3.5 w-3.5" />
          Save to project
        </button>
        <button type="button" onClick={() => downloadText(compose, 'compose.yaml', 'text/yaml')} className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50">
          <Download className="h-3.5 w-3.5" />
          Export compose
        </button>
        <button type="button" onClick={() => downloadText(dockerfile, 'Dockerfile', 'text/plain')} className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50">
          <Download className="h-3.5 w-3.5" />
          Export Dockerfile
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t border-zinc-100 pt-3">
        {(['up', 'ps', 'logs', 'down'] as const).map((action) => (
          <button
            key={action}
            type="button"
            disabled={!canRunContainer || runAction.isPending}
            onClick={() => run(action)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-40"
          >
            {runAction.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            {action === 'up' ? 'Start' : action === 'down' ? 'Stop' : action === 'ps' ? 'Status' : 'Logs'}
          </button>
        ))}
        <span className="text-xs text-zinc-500">
          {readOnly ? 'Container actions are disabled in --read-only mode.' : 'Only allowlisted docker compose subcommands are run.'}
        </span>
      </div>

      {output && (
        <pre className="max-h-64 overflow-y-auto rounded-lg border border-zinc-200 bg-zinc-50 p-3 font-mono text-xs whitespace-pre-wrap text-zinc-700">
          {output}
        </pre>
      )}
    </div>
  );
}

function EmptyBox({ text }: { text: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-zinc-200 bg-white px-6 py-12 text-center text-sm text-zinc-500">
      {text}
    </div>
  );
}

function DialogShell({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/30 p-4 backdrop-blur-[1px]"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-zinc-100 px-5 py-4">
          <h2 className="text-sm font-semibold text-zinc-900">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

/** Model picker shared by the Provider, Bee and Hive dialogs: the list comes
 * from provider model auto-detection, a custom name can still be typed, and the
 * selected model can be health-checked with one minimal completion. */
function ModelPicker({
  label,
  value,
  onChange,
  provider,
  inlineConfig,
}: {
  label: string;
  value: string;
  onChange: (model: string) => void;
  provider: Provider | null;
  inlineConfig?: { provider_type: string; base_url: string; api_key_env: string };
}) {
  const { readOnly } = useAppContext();
  const detect = useDetectProviderModels();
  const test = useTestProviderModel();
  const [detected, setDetected] = useState<Record<string, string[]>>({});
  const [testResult, setTestResult] = useState<ProviderModelTestResponse | null>(null);
  const key = provider?.alias ?? '__unsaved__';
  const models = detected[key] ?? provider?.available_models ?? [];

  const config = {
    provider_type: provider?.provider_type ?? inlineConfig?.provider_type ?? '',
    base_url: provider?.base_url ?? inlineConfig?.base_url ?? '',
    api_key_env: provider?.api_key_env ?? inlineConfig?.api_key_env ?? 'NONE',
  };

  const runDetect = (refresh: boolean) => {
    detect.mutate(
      provider ? { alias: provider.alias, refresh } : { ...config, refresh },
      {
        onSuccess: (res) => {
          setDetected((prev) => ({ ...prev, [key]: res.models }));
          if (res.models.length === 0 && !value) {
            setTestResult({
              success: false,
              detail: 'No models detected — check base_url / API key env var or type the model name.',
              model: null,
              latency_ms: 0,
            });
          }
        },
        onError: (ex) =>
          setTestResult({
            success: false,
            detail: ex instanceof Error ? ex.message : 'Model detection failed',
            model: null,
            latency_ms: 0,
          }),
      },
    );
  };

  // Probe once per dialog instance when nothing is cached for this provider.
  const probed = useRef(false);
  useEffect(() => {
    if (probed.current) return;
    probed.current = true;
    if (models.length === 0 && (provider || config.provider_type)) runDetect(false);
  }, []);

  const runTest = () => {
    if (!value) return;
    setTestResult(null);
    test.mutate(
      {
        alias: provider?.alias ?? null,
        provider_type: config.provider_type,
        base_url: config.base_url || null,
        api_key_env: config.api_key_env || 'NONE',
        model: value,
      },
      {
        onSuccess: (res) => setTestResult(res),
        onError: (ex) =>
          setTestResult({
            success: false,
            detail: ex instanceof Error ? ex.message : 'Model test failed',
            model: value,
            latency_ms: 0,
          }),
      },
    );
  };

  return (
    <Field label={label}>
      <div className="flex items-center gap-2">
        {models.length > 0 ? (
          <select
            value={value}
            onChange={(e) => {
              onChange(e.target.value);
              setTestResult(null);
            }}
            className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 font-mono text-sm"
          >
            {value && !models.includes(value) && (
              <option value={value}>{value} (current/custom)</option>
            )}
            {models.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))}
          </select>
        ) : (
          <input
            value={value}
            onChange={(e) => {
              onChange(e.target.value);
              setTestResult(null);
            }}
            placeholder="model name (e.g. gpt-4o-mini)"
            className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-sm"
          />
        )}
        <button
          type="button"
          onClick={() => runDetect(true)}
          disabled={detect.isPending}
          title="Fetch the models this provider reports"
          className="shrink-0 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50"
        >
          {detect.isPending ? 'Detecting…' : 'Detect models'}
        </button>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        <button
          type="button"
          onClick={runTest}
          disabled={test.isPending || !value || readOnly}
          title={readOnly ? 'Model testing is disabled in read-only mode' : 'Send one minimal completion to this model'}
          className="rounded-lg border border-zinc-200 bg-white px-3 py-1.5 font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50"
        >
          {test.isPending ? 'Testing…' : 'Test model'}
        </button>
        {testResult ? (
          <span className={testResult.success ? 'text-emerald-700' : 'text-rose-700'}>
            {testResult.success
              ? `OK in ${testResult.latency_ms} ms — ${testResult.detail}`
              : `${testResult.detail}`}
          </span>
        ) : (
          <span className="text-zinc-400">
            {value ? `${models.length} model(s) available` : 'Select a model (detect or type one).'}
          </span>
        )}
      </div>
    </Field>
  );
}

function ProviderDialog({
  initial,
  saving,
  onClose,
  onSave,
}: {
  initial: Provider | null;
  saving: boolean;
  onClose: () => void;
  onSave: (
    data: {
      alias: string;
      provider_type: string;
      base_url: string | null;
      api_key_env: string;
      default_model: string | null;
      input_cost_per_1m: number;
      output_cost_per_1m: number;
      context_window_tokens: number;
    },
    isEdit: boolean,
  ) => Promise<void>;
}) {
  const [alias, setAlias] = useState(initial?.alias ?? '');
  const [providerType, setProviderType] = useState(initial?.provider_type ?? 'openai');
  const [baseUrl, setBaseUrl] = useState(initial?.base_url ?? '');
  const [apiKeyEnv, setApiKeyEnv] = useState(initial?.api_key_env ?? 'OPENAI_API_KEY');
  const [defaultModel, setDefaultModel] = useState(initial?.default_model ?? '');
  const [inputCost, setInputCost] = useState(String(initial?.input_cost_per_1m ?? 0));
  const [outputCost, setOutputCost] = useState(String(initial?.output_cost_per_1m ?? 0));
  const [contextWindow, setContextWindow] = useState(String(initial?.context_window_tokens ?? 128000));
  const [err, setErr] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      await onSave(
        {
          alias: alias.trim(),
          provider_type: providerType,
          base_url: baseUrl.trim() || null,
          api_key_env: apiKeyEnv.trim() || 'NONE',
          default_model: defaultModel.trim() || null,
          input_cost_per_1m: parseFloat(inputCost) || 0,
          output_cost_per_1m: parseFloat(outputCost) || 0,
          context_window_tokens: parseInt(contextWindow, 10) || 128000,
        },
        Boolean(initial),
      );
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : 'Save failed');
    }
  };

  return (
    <DialogShell title={initial ? `Edit Provider · ${initial.alias}` : 'Add Provider'} onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col overflow-hidden">
        <div className="space-y-3.5 overflow-y-auto p-5 text-sm">
          {err && <p className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{err}</p>}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Alias">
              <input
                required
                disabled={Boolean(initial)}
                value={alias}
                onChange={(e) => setAlias(e.target.value)}
                placeholder="openai"
                className="w-full rounded-lg border border-zinc-200 px-3 py-2 text-sm disabled:bg-zinc-50"
              />
            </Field>
            <Field label="Provider Type">
              <select
                value={providerType}
                onChange={(e) => setProviderType(e.target.value)}
                className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm"
              >
                <option value="openai">openai</option>
                <option value="anthropic">anthropic</option>
                <option value="google_genai">google_genai (Gemini)</option>
                <option value="openai_compatible">openai_compatible</option>
              </select>
            </Field>
          </div>
          {providerType === 'openai_compatible' && (
            <Field label="Base URL">
              <input
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="http://localhost:11434/v1"
                className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs"
              />
            </Field>
          )}
          <Field label="API Key Env Var">
            <input
              required
              value={apiKeyEnv}
              onChange={(e) => setApiKeyEnv(e.target.value)}
              placeholder="OPENAI_API_KEY or NONE"
              className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs"
            />
          </Field>

          <ModelPicker
            label="Model (auto-detected)"
            value={defaultModel}
            onChange={setDefaultModel}
            provider={initial}
            inlineConfig={{
              provider_type: providerType,
              base_url: baseUrl.trim(),
              api_key_env: apiKeyEnv.trim() || 'NONE',
            }}
          />

          <div className="grid grid-cols-3 gap-3">
            <Field label="Input $/1M">
              <input
                type="number"
                step="0.0001"
                value={inputCost}
                onChange={(e) => setInputCost(e.target.value)}
                className="w-full rounded-lg border border-zinc-200 px-3 py-2 text-sm"
              />
            </Field>
            <Field label="Output $/1M">
              <input
                type="number"
                step="0.0001"
                value={outputCost}
                onChange={(e) => setOutputCost(e.target.value)}
                className="w-full rounded-lg border border-zinc-200 px-3 py-2 text-sm"
              />
            </Field>
            <Field label="Context Tokens">
              <input
                type="number"
                value={contextWindow}
                onChange={(e) => setContextWindow(e.target.value)}
                className="w-full rounded-lg border border-zinc-200 px-3 py-2 text-sm"
              />
            </Field>
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t border-zinc-100 bg-zinc-50/70 px-5 py-3">
          <button type="button" onClick={onClose} className="rounded-lg border border-zinc-200 bg-white px-3.5 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50">
            Cancel
          </button>
          <button type="submit" disabled={saving} className="rounded-lg bg-zinc-900 px-4 py-1.5 text-xs font-medium text-white hover:bg-zinc-800 disabled:opacity-50">
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </DialogShell>
  );
}

function BeeDialog({
  initial,
  providers,
  tools,
  saving,
  onClose,
  onSave,
}: {
  initial: Bee | null;
  providers: Provider[];
  tools: ToolSchema[];
  saving: boolean;
  onClose: () => void;
  onSave: (
    data: {
      name: string;
      role_description: string;
      system_prompt: string;
      provider_id: number;
      model_name: string;
      temperature: number;
      thinking_level: string;
      tool_names: string[];
      require_approval: string[];
    },
    isEdit: boolean,
  ) => Promise<void>;
}) {
  const [name, setName] = useState(initial?.name ?? '');
  const [providerId, setProviderId] = useState<number>(initial?.provider_id ?? providers[0]?.id ?? 0);
  const [modelName, setModelName] = useState(
    initial?.model_name ?? providers[0]?.default_model ?? '',
  );
  const selectedProvider = providers.find((p) => p.id === providerId) ?? null;

  const chooseProvider = (id: number) => {
    setProviderId(id);
    const provider = providers.find((p) => p.id === id);
    if (provider && modelName && !provider.available_models?.includes(modelName)) {
      setModelName(provider.default_model ?? provider.assistant_model ?? provider.available_models?.[0] ?? modelName);
    }
  };
  const [roleDescription, setRoleDescription] = useState(initial?.role_description ?? '');
  const [systemPrompt, setSystemPrompt] = useState(initial?.system_prompt ?? '');
  const [temperature, setTemperature] = useState(String(initial?.temperature ?? 0));
  const [thinkingLevel, setThinkingLevel] = useState(initial?.thinking_level ?? 'off');
  const [selectedTools, setSelectedTools] = useState<string[]>(initial?.tool_names ?? []);
  const [gatedTools, setGatedTools] = useState<string[]>(initial?.require_approval ?? []);
  const [err, setErr] = useState<string | null>(null);

  const toggleTool = (toolName: string) => {
    if (selectedTools.includes(toolName)) {
      setSelectedTools((prev) => prev.filter((t) => t !== toolName));
      setGatedTools((prev) => prev.filter((t) => t !== toolName));
    } else {
      setSelectedTools((prev) => [...prev, toolName]);
    }
  };

  const toggleGate = (toolName: string) => {
    if (!selectedTools.includes(toolName)) {
      setSelectedTools((prev) => [...prev, toolName]);
    }
    setGatedTools((prev) =>
      prev.includes(toolName) ? prev.filter((t) => t !== toolName) : [...prev, toolName],
    );
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    if (!modelName.trim()) {
      setErr('Pick or type a model name before saving this Bee.');
      return;
    }
    try {
      await onSave(
        {
          name: name.trim(),
          role_description: roleDescription.trim(),
          system_prompt: systemPrompt,
          provider_id: providerId,
          model_name: modelName.trim(),
          temperature: parseFloat(temperature) || 0,
          thinking_level: thinkingLevel,
          tool_names: selectedTools,
          require_approval: gatedTools.filter((t) => selectedTools.includes(t)),
        },
        Boolean(initial),
      );
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : 'Save failed');
    }
  };

  return (
    <DialogShell title={initial ? `Edit Bee · ${initial.name}` : 'New Worker Bee'} onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col overflow-hidden">
        <div className="space-y-3.5 overflow-y-auto p-5 text-sm">
          {err && <p className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{err}</p>}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Name">
              <input
                required
                disabled={Boolean(initial)}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="coder-bee"
                className="w-full rounded-lg border border-zinc-200 px-3 py-2 text-sm disabled:bg-zinc-50"
              />
            </Field>
            <Field label="Provider">
              <select
                value={providerId}
                onChange={(e) => chooseProvider(Number(e.target.value))}
                className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm"
              >
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.alias} ({p.provider_type})
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <ModelPicker label="Model (auto-detected)" value={modelName} onChange={setModelName} provider={selectedProvider} />
          <div className="grid grid-cols-2 gap-3">
            <Field label="Temperature">
              <input
                type="number"
                step="0.1"
                min="0"
                max="2"
                value={temperature}
                onChange={(e) => setTemperature(e.target.value)}
                className="w-full rounded-lg border border-zinc-200 px-3 py-2 text-sm"
              />
            </Field>
            <Field label="Thinking">
              <select
                value={thinkingLevel}
                onChange={(e) => setThinkingLevel(e.target.value)}
                className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm"
              >
                <option value="off">off</option>
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
            </Field>
          </div>
          <Field label="Role Description">
            <input
              required
              value={roleDescription}
              onChange={(e) => setRoleDescription(e.target.value)}
              placeholder="Writes and tests Python code..."
              className="w-full rounded-lg border border-zinc-200 px-3 py-2 text-sm"
            />
          </Field>
          <Field label="System Prompt">
            <textarea
              rows={3}
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="You are a careful software engineer..."
              className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs"
            />
          </Field>

          {/* Tool & Approval Permission Matrix (from GET /api/v1/tools) */}
          <Field label="Tools & HITL Approval Matrix">
            <div className="overflow-hidden rounded-xl border border-zinc-200">
              <table className="w-full border-collapse text-left text-xs">
                <thead>
                  <tr className="border-b border-zinc-100 bg-zinc-50 text-[11px] text-zinc-500">
                    <th className="px-3 py-2">Tool</th>
                    <th className="px-3 py-2 text-center w-20">Enabled</th>
                    <th className="px-3 py-2 text-center w-28">Require Approval</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100">
                  {tools.map((tool) => {
                    const enabled = selectedTools.includes(tool.name);
                    const gated = gatedTools.includes(tool.name);
                    return (
                      <tr key={tool.name} className="hover:bg-zinc-50/70">
                        <td className="px-3 py-2">
                          <div className="font-mono font-medium text-zinc-800">{tool.name}</div>
                          {tool.description && (
                            <div className="truncate max-w-[260px] text-[11px] text-zinc-400">
                              {tool.description}
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-2 text-center">
                          <input
                            type="checkbox"
                            checked={enabled}
                            onChange={() => toggleTool(tool.name)}
                            className="h-4 w-4 rounded border-zinc-300 accent-zinc-900"
                          />
                        </td>
                        <td className="px-3 py-2 text-center">
                          <input
                            type="checkbox"
                            checked={gated}
                            onChange={() => toggleGate(tool.name)}
                            className="h-4 w-4 rounded border-zinc-300 accent-amber-600"
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Field>
        </div>
        <div className="flex justify-end gap-2 border-t border-zinc-100 bg-zinc-50/70 px-5 py-3">
          <button type="button" onClick={onClose} className="rounded-lg border border-zinc-200 bg-white px-3.5 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50">
            Cancel
          </button>
          <button type="submit" disabled={saving} className="rounded-lg bg-zinc-900 px-4 py-1.5 text-xs font-medium text-white hover:bg-zinc-800 disabled:opacity-50">
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </DialogShell>
  );
}

function HiveDialog({
  initial,
  providers,
  bees,
  saving,
  onClose,
  onSave,
}: {
  initial: Hive | null;
  providers: Provider[];
  bees: Bee[];
  saving: boolean;
  onClose: () => void;
  onSave: (
    data: {
      name: string;
      goal_description: string | null;
      supervisor_provider_id: number;
      supervisor_model_name: string;
      supervisor_prompt: string | null;
      supervisor_thinking_level: string;
      is_dynamic: boolean;
      project_path: string | null;
      bee_ids: number[];
    },
    isEdit: boolean,
  ) => Promise<void>;
}) {
  const [name, setName] = useState(initial?.name ?? '');
  const [providerId, setProviderId] = useState<number>(
    initial?.supervisor_provider_id ?? providers[0]?.id ?? 0,
  );
  const [modelName, setModelName] = useState(
    initial?.supervisor_model_name ?? providers[0]?.default_model ?? '',
  );
  const selectedProvider = providers.find((p) => p.id === providerId) ?? null;

  const chooseProvider = (id: number) => {
    setProviderId(id);
    const provider = providers.find((p) => p.id === id);
    if (provider && modelName && !provider.available_models?.includes(modelName)) {
      setModelName(provider.default_model ?? provider.available_models?.[0] ?? modelName);
    }
  };
  const [goalDesc, setGoalDesc] = useState(initial?.goal_description ?? '');
  const [supPrompt, setSupPrompt] = useState(initial?.supervisor_prompt ?? '');
  const [thinking, setThinking] = useState(initial?.supervisor_thinking_level ?? 'medium');
  const [projectPath, setProjectPath] = useState(initial?.project_path ?? '');
  const [isDynamic, setIsDynamic] = useState(initial?.is_dynamic ?? false);
  const [beeIds, setBeeIds] = useState<number[]>(initial?.bee_ids ?? []);
  const [err, setErr] = useState<string | null>(null);

  const toggleBee = (id: number) => {
    setBeeIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    if (!modelName.trim()) {
      setErr('Pick or type a model name before saving this Hive.');
      return;
    }
    try {
      await onSave(
        {
          name: name.trim(),
          goal_description: goalDesc.trim() || null,
          supervisor_provider_id: providerId,
          supervisor_model_name: modelName.trim(),
          supervisor_prompt: supPrompt.trim() || null,
          supervisor_thinking_level: thinking,
          is_dynamic: isDynamic,
          project_path: projectPath.trim() || null,
          bee_ids: beeIds,
        },
        Boolean(initial),
      );
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : 'Save failed');
    }
  };

  return (
    <DialogShell title={initial ? `Edit Hive · ${initial.name}` : 'New Hive'} onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col overflow-hidden">
        <div className="space-y-3.5 overflow-y-auto p-5 text-sm">
          {err && <p className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{err}</p>}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Name">
              <input
                required
                disabled={Boolean(initial)}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="dev-team"
                className="w-full rounded-lg border border-zinc-200 px-3 py-2 text-sm disabled:bg-zinc-50"
              />
            </Field>
            <Field label="Supervisor Provider">
              <select
                value={providerId}
                onChange={(e) => chooseProvider(Number(e.target.value))}
                className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm"
              >
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.alias} ({p.provider_type})
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <ModelPicker
            label="Supervisor Model (auto-detected)"
            value={modelName}
            onChange={setModelName}
            provider={selectedProvider}
          />
          <Field label="Supervisor Thinking">
            <select
              value={thinking}
              onChange={(e) => setThinking(e.target.value)}
              className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm"
            >
              <option value="off">off</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
            </select>
          </Field>
          <Field label="Goal Description">
            <input
              value={goalDesc}
              onChange={(e) => setGoalDesc(e.target.value)}
              placeholder="Optional description of what this Hive handles..."
              className="w-full rounded-lg border border-zinc-200 px-3 py-2 text-sm"
            />
          </Field>
          <Field label="Project Path (optional)">
            <input
              value={projectPath}
              onChange={(e) => setProjectPath(e.target.value)}
              placeholder="./artifacts/dev-team"
              className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs"
            />
          </Field>
          <Field label="Supervisor Prompt (optional)">
            <textarea
              rows={3}
              value={supPrompt}
              onChange={(e) => setSupPrompt(e.target.value)}
              placeholder="Leave blank to use default Supervisor routing prompt..."
              className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs"
            />
          </Field>
          <Field label="Member Worker Bees">
            {bees.length === 0 ? (
              <p className="text-xs text-zinc-400">No Worker Bees created yet.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {bees.map((b) => (
                  <label
                    key={b.id}
                    className={cn(
                      'inline-flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-xs transition-colors',
                      beeIds.includes(b.id)
                        ? 'border-amber-400 bg-amber-50 text-amber-900'
                        : 'border-zinc-200 bg-white text-zinc-600 hover:bg-zinc-50',
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={beeIds.includes(b.id)}
                      onChange={() => toggleBee(b.id)}
                      className="accent-amber-600"
                    />
                    {b.name}
                  </label>
                ))}
              </div>
            )}
          </Field>
          <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-zinc-600">
            <input
              type="checkbox"
              checked={isDynamic}
              onChange={(e) => setIsDynamic(e.target.checked)}
              className="accent-zinc-900"
            />
            Dynamic Hive
          </label>
        </div>
        <div className="flex justify-end gap-2 border-t border-zinc-100 bg-zinc-50/70 px-5 py-3">
          <button type="button" onClick={onClose} className="rounded-lg border border-zinc-200 bg-white px-3.5 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50">
            Cancel
          </button>
          <button type="submit" disabled={saving} className="rounded-lg bg-zinc-900 px-4 py-1.5 text-xs font-medium text-white hover:bg-zinc-800 disabled:opacity-50">
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </DialogShell>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="block text-xs font-medium text-zinc-600">{label}</span>
      {children}
    </label>
  );
}

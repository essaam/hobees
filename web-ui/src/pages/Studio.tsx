import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  AlertTriangle,
  Bot,
  Check,
  Code2,
  Container,
  Copy,
  Download,
  Edit3,
  Key,
  Layers,
  LayoutGrid,
  Loader2,
  Plus,
  Search,
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
  useApplyTemplate,
  useCreateBee,
  useCreateHive,
  useCreateProvider,
  useDeleteBee,
  useDeleteHive,
  useDeleteProvider,
  useDeleteSkill,
  useDetectProviderModels,
  useDetectProviders,
  useHives,
  useImportConfigYaml,
  useProviders,
  useRegisterDetectedProviders,
  useResetPlan,
  useResetSlate,
  useSaveLastSkill,
  useSkills,
  useTemplates,
  useTestProviderModel,
  useTools,
  useUpdateBee,
  useUpdateHive,
  useUpdateProvider,
} from '../hooks/useApi';
import type {
  Bee,
  ContainerSpec,
  DetectedProvider,
  Hive,
  Provider,
  ProviderModelTestResponse,
  ResetResponse,
  TemplateAction,
  TemplateItem,
  ToolSchema,
} from '../types';
import { cn, copyText, downloadText, formatBytes } from '../utils/helpers';

type StudioTab = 'setup' | 'hives' | 'bees' | 'providers' | 'skills' | 'containers';

const STUDIO_TABS: StudioTab[] = ['setup', 'hives', 'bees', 'providers', 'skills', 'containers'];

export function Studio() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { readOnly } = useAppContext();

  const initialTab = (searchParams.get('tab') as StudioTab) || '';
  const [tab, setTab] = useState<StudioTab>(STUDIO_TABS.includes(initialTab) ? initialTab : 'setup');
  const [viewMode, setViewMode] = useState<'visual' | 'yaml'>(
    searchParams.get('mode') === 'yaml' ? 'yaml' : 'visual',
  );

  const { data: providers = [], isLoading: providersLoading } = useProviders();
  const { data: bees = [], isLoading: beesLoading } = useBees();
  const { data: hives = [], isLoading: hivesLoading } = useHives();
  const { data: skills = [] } = useSkills();
  const { data: toolsData } = useTools();
  const tools = toolsData?.tools ?? [];
  const { data: containerList } = useContainers();
  const { data: templates = [] } = useTemplates();

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

  // Quick setup is the landing tab only while the slate is still empty. Once the first
  // data arrives, an install that already has providers/Bees/Hives lands on Hives as
  // before, and an explicit ?tab= always wins over this.
  const [defaultTabResolved, setDefaultTabResolved] = useState(STUDIO_TABS.includes(initialTab));

  useEffect(() => {
    if (defaultTabResolved || searchParams.get('tab')) return;
    if (providersLoading || beesLoading || hivesLoading) return;
    setDefaultTabResolved(true);
    if (providers.length + bees.length + hives.length > 0) setTab('hives');
  }, [
    defaultTabResolved,
    providers,
    bees,
    hives,
    providersLoading,
    beesLoading,
    hivesLoading,
    searchParams,
  ]);

  useEffect(() => {
    const t = searchParams.get('tab') as StudioTab | null;
    if (t && STUDIO_TABS.includes(t)) {
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
                  { id: 'setup', label: 'Quick setup', count: templates.length, icon: Layers },
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
            {tab === 'setup' && <QuickSetupTab readOnly={readOnly} />}
            {tab === 'providers' && <ProviderDetectionPanel readOnly={readOnly} />}
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

  const [fields, setFields] = useState({
    service: 'hobees',
    image: 'hobees:local',
    base_image: 'python:3.12-slim',
    container_name: '',
    profiles: 'pipeline',
    ports: '6543:6543',
    volumes: './output:/home/hobees/output, ./skills:/home/hobees/skills',
    command: '',
    include_db: true,
    postgres_service_name: 'postgres',
    run_hive: '',
    goal: '',
    goal_mode: 'mount' as ContainerSpec['goal_mode'],
    run_init: true,
    include_web: false,
  });
  const [compose, setCompose] = useState('');
  const [dockerfile, setDockerfile] = useState('');
  const [config, setConfig] = useState('');
  const [entrypoint, setEntrypoint] = useState('');
  const [pipeline, setPipeline] = useState<string[]>([]);
  const [envSample, setEnvSample] = useState('');
  const [warnings, setWarnings] = useState<string[]>([]);
  const [output, setOutput] = useState('');
  const synced = useRef('');
  const dirty = JSON.stringify(fields) !== synced.current;

  const { data: hiveList = [] } = useHives();

  useEffect(() => {
    if (!plan) return;
    setCompose(plan.compose);
    setDockerfile(plan.dockerfile);
    setConfig(plan.config);
    setEntrypoint(plan.entrypoint);
    setPipeline(plan.pipeline_command);
    setEnvSample(plan.env_sample);
    setWarnings(plan.warnings);
    setFields((prev) => {
      const next = {
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
        postgres_service_name: plan.spec.postgres_service_name,
        run_hive: plan.spec.run_hive,
        goal: plan.spec.goal,
        goal_mode: plan.spec.goal_mode,
        run_init: plan.spec.run_init,
        include_web: plan.spec.include_web,
      };
      synced.current = JSON.stringify(next);
      return next;
    });
  }, [plan]);

  const list = (value: string) => value.split(',').map((item) => item.trim()).filter(Boolean);

  const spec = (): ContainerSpec => ({
    project: plan?.spec.project ?? 'hobees',
    service: fields.service,
    image: fields.image,
    container_name: fields.container_name,
    base_image: fields.base_image,
    working_dir: plan?.spec.working_dir ?? '/home/hobees',
    user: plan?.spec.user ?? '${HOBEES_UID:-1000}:${HOBEES_GID:-1000}',
    // The image ENTRYPOINT is the generated script; only an explicit override belongs here.
    entrypoint: plan?.spec.entrypoint ?? [],
    command: list(fields.command),
    profiles: list(fields.profiles),
    restart: plan?.spec.restart ?? 'no',
    ports: list(fields.ports),
    volumes: list(fields.volumes),
    init: plan?.spec.init ?? true,
    extra_hosts: plan?.spec.extra_hosts ?? ['host.docker.internal:host-gateway'],
    init_service: plan?.spec.init_service ?? 'init-dirs',
    init_image: plan?.spec.init_image ?? 'alpine:3.20',
    init_workspace: plan?.spec.init_workspace ?? '/workspace',
    output_dir: plan?.spec.output_dir ?? 'output',
    skills_dir: plan?.spec.skills_dir ?? 'skills',
    env: plan?.spec.env ?? {},
    api_key_envs: plan?.spec.api_key_envs ?? [],
    include_db: fields.include_db,
    db_image: plan?.spec.db_image ?? 'postgres:16-alpine',
    db_volume: plan?.spec.db_volume ?? 'postgres_data',
    db_name: plan?.spec.db_name ?? 'hobeesdb',
    db_user: plan?.spec.db_user ?? 'hobees',
    postgres_service_name: fields.postgres_service_name,
    config_file: plan?.spec.config_file ?? 'hobees.yaml',
    config_dir: plan?.spec.config_dir ?? 'config',
    goal: fields.goal,
    goal_file: plan?.spec.goal_file ?? 'goal.txt',
    goal_mode: fields.goal_mode,
    run_hive: fields.run_hive,
    run_init: fields.run_init,
    entrypoint_file: plan?.spec.entrypoint_file ?? 'docker-entrypoint.sh',
    web_service_name: plan?.spec.web_service_name ?? 'web',
    include_web: fields.include_web,
  });

  // The run command, the config, the entrypoint script and the goal all follow the settings
  // in this panel, so previewing must refresh the whole plan, not only compose/Dockerfile.
  const preview = async () => {
    setOutput('');
    try {
      const sent = spec();
      const res = await buildPlan.mutateAsync(sent);
      synced.current = JSON.stringify(sent);
      setCompose(res.compose);
      setDockerfile(res.dockerfile);
      setConfig(res.config);
      setEntrypoint(res.entrypoint);
      setEnvSample(res.env_sample);
      setPipeline(res.pipeline_command);
      setWarnings(res.warnings);
    } catch (err) {
      setOutput(err instanceof Error ? err.message : 'Preview failed');
    }
  };

  const save = async () => {
    if (readOnly) return;
    try {
      const res = await saveFiles.mutateAsync({
        compose,
        dockerfile,
        config,
        entrypoint,
        goal: fields.goal_mode === 'stdin' ? '' : fields.goal,
        env_sample: envSample,
        spec: spec(),
      });
      setOutput(`Saved ${res.saved.join(', ') || 'nothing (empty content was skipped)'}`);
      setWarnings(res.warnings);
    } catch (err) {
      setOutput(err instanceof Error ? err.message : 'Save failed');
    }
  };

  // One download per file, not a pack: staggered so the browser does not swallow the rest.
  const generatedFiles = () => [
    { name: 'compose.yaml', content: compose, mime: 'text/yaml' },
    { name: 'Dockerfile', content: dockerfile, mime: 'text/plain' },
    { name: 'hobees.yaml', content: config, mime: 'text/yaml' },
    { name: 'docker-entrypoint.sh', content: entrypoint, mime: 'text/plain' },
    { name: '.env.sample', content: envSample, mime: 'text/plain' },
    { name: 'goal.txt', content: fields.goal_mode === 'stdin' ? '' : fields.goal, mime: 'text/plain' },
  ];

  const downloadAll = () => {
    const items = generatedFiles().filter((item) => item.content.trim());
    items.forEach((item, index) => setTimeout(() => downloadText(item.content, item.name, item.mime), index * 200));
    setOutput(`Downloaded ${items.length} file${items.length === 1 ? '' : 's'} separately`);
  };

  // The host folders compose bind-mounts: init-dirs creates them and chowns them to the
  // container user, so a run on a new machine needs only .env, not a manual mkdir.
  const preparedDirs = () => {
    const hosts = list(fields.volumes)
      .map((mount) => mount.split(':')[0])
      .filter((host) => host.startsWith('./'))
      .map((host) => host.slice(2).split('/')[0]);
    const dbVolume = plan?.spec.db_volume ?? 'postgres_data';
    if (fields.include_db && dbVolume.startsWith('./')) hosts.push(dbVolume.slice(2).split('/')[0]);
    return hosts.filter(Boolean);
  };

  // A bare name is a Docker volume, not a host folder, so init-dirs cannot prepare it: it is
  // declared in the top-level `volumes:` block at the bottom of compose.yaml instead.
  const namedVolumes = () => {
    const isName = (source: string) =>
      Boolean(source) && source !== '.' && source !== '..' && !source.startsWith('./') && !source.includes('/') && !source.includes('\\');
    const names = list(fields.volumes).map((mount) => mount.split(':')[0]).filter(isName);
    const dbVolume = plan?.spec.db_volume ?? 'postgres_data';
    if (fields.include_db && isName(dbVolume) && !names.includes(dbVolume)) names.push(dbVolume);
    return names;
  };

  // `docker compose run` starts a service from a profile, so the command follows the
  // profile field: one --profile per value, the service key, then the args typed above.
  // In stdin mode there is no goal file, so the pipe needs -T (no TTY).
  const runCommand = () => {
    const profiles = list(fields.profiles).map((profile) => `--profile ${profile}`);
    const tty = fields.goal_mode === 'stdin' ? ' -T' : '';
    return [
      'docker compose',
      profiles.join(' '),
      `run${tty} --rm`,
      fields.service,
      fields.command.trim(),
    ].filter(Boolean).join(' ');
  };

  if (isLoading || !plan) return <EmptyBox text="Reading the container plan…" />;

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
        <Field label="Postgres service name (the compose key and the host the container resolves)">
          <input value={fields.postgres_service_name} onChange={(e) => setFields((prev) => ({ ...prev, postgres_service_name: e.target.value }))} readOnly={readOnly} className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs" />
        </Field>
        <Field label="Volumes (host:container or volume:container, comma-separated)">
          <input value={fields.volumes} onChange={(e) => setFields((prev) => ({ ...prev, volumes: e.target.value }))} readOnly={readOnly} className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs" />
        </Field>
        <Field label="Command args (override only - the entrypoint script decides what runs)">
          <input value={fields.command} onChange={(e) => setFields((prev) => ({ ...prev, command: e.target.value }))} readOnly={readOnly} className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs" />
        </Field>
      </div>

      {/* Run the goal: the container is built to carry the config and run one goal */}
      <div className="space-y-3 rounded-lg border border-zinc-200 bg-zinc-50/60 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-semibold text-zinc-800">Run for this goal</span>
          <div className="inline-flex rounded-lg border border-zinc-200 bg-white p-0.5 text-xs font-medium">
            {(['mount', 'bake', 'stdin'] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setFields((prev) => ({ ...prev, goal_mode: mode }))}

                disabled={readOnly}
                className={cn(
                  'rounded-md px-2.5 py-1 transition-colors',
                  fields.goal_mode === mode ? 'bg-zinc-900 text-white' : 'text-zinc-600 hover:text-zinc-900',
                )}
              >
                {mode}
              </button>
            ))}
          </div>
        </div>

        <Field label="Goal (written to goal.txt at the project root)">
          <textarea
            value={fields.goal}
            onChange={(e) => setFields((prev) => ({ ...prev, goal: e.target.value }))}
            readOnly={readOnly}
            spellCheck={false}
            rows={5}
            placeholder="Review src/ for race conditions and propose fixes"
            className="w-full resize-y rounded-lg border border-zinc-200 px-3 py-2 text-xs leading-relaxed focus:outline-none focus:border-zinc-400"
          />
        </Field>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Run hive (empty = Queen auto-mode)">
            <select
              value={fields.run_hive}
              onChange={(e) => setFields((prev) => ({ ...prev, run_hive: e.target.value }))}
              disabled={readOnly}
              className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs"
            >
              <option value="">(auto-mode)</option>
              {hiveList.map((hive) => (
                <option key={hive.id} value={hive.name}>{hive.name}</option>
              ))}
            </select>
          </Field>
          <p className="text-xs text-zinc-500">
        This tab only writes files - nothing here starts or stops a container, so the command above is run by you
        (or by CI). Editing a field does not regenerate by itself: click
        <span className="font-medium text-zinc-700"> Update spec </span>
        to apply the settings to compose.yaml, the Dockerfile, hobees.yaml, the entrypoint script and the run command.
        {dirty ? <span className="font-medium text-amber-700"> Unapplied changes.</span> : null}
      </p>

      <p className="text-xs text-zinc-500">
        The container reads its values from <span className="font-mono">./.env</span>, so the generated files hold
        names only: <span className="font-mono">.env.sample</span> mirrors the sections the tested set uses (Host
        UID/GID mapping, Postgres credentials, Provider API keys, Hobees runtime configuration), and the
        service, image, container name, profiles, ports, volumes, Postgres service name and the goal come from
        the fields above.
      </p>

      <label className="flex items-center gap-2 text-xs text-zinc-600">
            <input type="checkbox" checked={fields.run_init} onChange={(e) => setFields((prev) => ({ ...prev, run_init: e.target.checked }))} disabled={readOnly} />
            entrypoint runs <span className="font-mono">hobees init --config</span> before the goal
          </label>
          <label className="flex items-center gap-2 text-xs text-zinc-600">
            <input type="checkbox" checked={fields.include_web} onChange={(e) => setFields((prev) => ({ ...prev, include_web: e.target.checked }))} disabled={readOnly} />
            include the web service (it stays commented out when off)
          </label>
        </div>

        <p className="text-xs text-zinc-500">
          {fields.goal_mode === 'mount'
            ? 'goal.txt is mounted read-only, so the goal can change per run without a rebuild.'
            : fields.goal_mode === 'bake'
              ? 'goal.txt is copied into the image: the goal is frozen in a layer and needs a rebuild.'
              : 'the goal is piped on stdin (run -T --rm, shown above), no file is written.'}
          {' '}The goal text is never written into the entrypoint script, so it can never be read as shell.
        </p>

        <div className="flex items-center justify-between gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-2">
          <div className="font-mono text-xs text-zinc-700 break-all">
            {runCommand()}
            <div className="mt-1 text-zinc-500">
              the script itself runs: {fields.run_init ? 'hobees init --config, then ' : ''}{pipeline.join(' ')}
            </div>
            {preparedDirs().length > 0 && (
              <div className="mt-1 text-zinc-500">
                <span className="font-mono">init-dirs</span> creates {preparedDirs().map((dir) => `./${dir}`).join(', ')} and hands them to
                {' '}{plan?.spec.user ?? '${HOBEES_UID:-1000}:${HOBEES_GID:-1000}'} before
                {' '}{fields.service} starts, so the bind mounts are writable without a rebuild.
              </div>
            )}
            {namedVolumes().length > 0 && (
              <div className="mt-1 text-zinc-500">
                {namedVolumes().map((name) => <span key={name} className="font-mono">{name}</span>).join(', ')} are Docker volumes, so
                {' '}they are declared in the <span className="font-mono">volumes:</span> block at the bottom of compose.yaml instead of being
                {' '}created on the host; <span className="font-mono">docker compose down -v</span> is what removes them.
              </div>
            )}
          </div>
          <div className="mt-2 text-xs text-zinc-500">
            The exit code is how a pipeline learns the outcome: 0 completed, 1 failed, 2 stopped for an approval,
            3 still running. It propagates through `docker run` / `docker compose run` even against a remote
            daemon. For a detached run, read it with
            {'docker inspect -f "{{.State.ExitCode}}" <container>'} or `docker compose up --exit-code-from {fields.service}`,
            or ask the run itself: {`hobees pipeline status --hive ${fields.run_hive || 'the hive'} --json --poll 5 --timeout 60`}.
            The manifest keeps the same code as `exit_code`.
          </div>
          <button
            type="button"
            onClick={() => {
              copyText(runCommand());
              setOutput('Run command copied');
            }}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-2.5 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50"
          >
            <Copy className="h-3.5 w-3.5" />
            Copy
          </button>
        </div>
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

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Field label={plan?.config_exists ? 'hobees.yaml (already saved at the project root)' : 'hobees.yaml (the active configuration)'}>
          <textarea value={config} onChange={(e) => setConfig(e.target.value)} readOnly={readOnly} spellCheck={false} rows={12} className="w-full resize-y rounded-lg border border-zinc-200 bg-zinc-950 p-3 font-mono text-xs leading-relaxed text-zinc-100 focus:outline-none" />
        </Field>
        <Field label="docker-entrypoint.sh (init, then the goal)">
          <textarea value={entrypoint} readOnly spellCheck={false} rows={12} className="w-full resize-y rounded-lg border border-zinc-200 bg-zinc-950 p-3 font-mono text-xs leading-relaxed text-zinc-100 focus:outline-none" />
        </Field>
        <Field label={plan?.env_sample_exists ? '.env.sample (already saved at the project root)' : '.env.sample (keys the generated files read, no values)'}>
          <textarea value={envSample} onChange={(e) => setEnvSample(e.target.value)} readOnly={readOnly} spellCheck={false} rows={12} className="w-full resize-y rounded-lg border border-zinc-200 bg-zinc-950 p-3 font-mono text-xs leading-relaxed text-zinc-100 focus:outline-none" />
        </Field>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" disabled={buildPlan.isPending} onClick={preview} className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50">
          <Code2 className="h-3.5 w-3.5" />
          {dirty ? 'Update spec (unapplied changes)' : 'Update spec'}
        </button>
        <button
          type="button"
          onClick={downloadAll}
          className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50"
        >
          <Download className="h-3.5 w-3.5" />
          Download all files
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
        <button type="button" onClick={() => downloadText(config, 'hobees.yaml', 'text/yaml')} className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50">
          <Download className="h-3.5 w-3.5" />
          Export hobees.yaml
        </button>
        <button type="button" onClick={() => downloadText(entrypoint, 'docker-entrypoint.sh', 'text/plain')} className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50">
          <Download className="h-3.5 w-3.5" />
          Export entrypoint
        </button>
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

/** Quick setup: built-in templates on top, Reset below. */
function QuickSetupTab({ readOnly }: { readOnly: boolean }) {
  return (
    <div className="space-y-3">
      <TemplatesPanel readOnly={readOnly} />
      <ResetPanel readOnly={readOnly} />
    </div>
  );
}

/** Browser twin of `hobees init --template <name>`.
 *
 * The server reports which names a blueprint already finds in the database, so a
 * collision is visible before applying. `skip` is the default: existing bees, hives,
 * skills, memories and providers are left exactly as they are. Overwriting is only
 * possible when the user confirms the collision list with Y (yes).
 */
function TemplatesPanel({ readOnly }: { readOnly: boolean }) {
  const { data: templates = [], isLoading } = useTemplates();
  const applyTemplate = useApplyTemplate();
  const [onConflict, setOnConflict] = useState<'skip' | 'overwrite'>('skip');
  const [confirming, setConfirming] = useState<TemplateItem | null>(null);
  const [answer, setAnswer] = useState('');
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const confirmed = ['y', 'yes'].includes(answer.trim().toLowerCase());

  const summarize = (actions: TemplateAction[]) => {
    const counts: Record<string, number> = {};
    for (const action of actions) counts[action.action] = (counts[action.action] ?? 0) + 1;
    return Object.entries(counts)
      .map(([word, count]) => `${count} ${word}`)
      .join(', ');
  };

  const apply = async (template: TemplateItem, needsConfirm: boolean) => {
    if (readOnly) return;
    // A blueprint that collides with existing names is only applied after Y(es).
    if (needsConfirm && !confirmed) return;
    setError(null);
    try {
      const res = await applyTemplate.mutateAsync({
        template: template.name,
        on_conflict: onConflict,
        confirmed: needsConfirm,
      });
      setStatus(`Applied ${res.template} (${res.on_conflict}): ${summarize(res.actions)}`);
      setConfirming(null);
      setAnswer('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not apply template');
    }
  };

  return (
    <div className="rounded-2xl border border-zinc-200/90 bg-white p-4 shadow-sm sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-zinc-900">Templates</h2>
          <p className="mt-1 max-w-2xl text-xs text-zinc-500">
            Built-in starter blueprints. Applying one creates its providers, Bees, Hives, skills
            and assistant. An import writes by name, so a blueprint can reach entries that are
            already set up — pick what happens to those.
          </p>
        </div>
        <div className="inline-flex rounded-lg border border-zinc-200 bg-white p-0.5 text-xs font-medium">
          {(['skip', 'overwrite'] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setOnConflict(mode)}
              className={cn(
                'rounded-md px-3 py-1.5 transition-colors',
                onConflict === mode ? 'bg-zinc-900 text-white' : 'text-zinc-600 hover:text-zinc-900',
              )}
            >
              {mode === 'skip' ? 'Skip existing' : 'Overwrite existing'}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <p className="mt-3 text-xs text-zinc-400">Loading templates…</p>
      ) : (
        <div className="mt-3 space-y-2.5">
          {templates.map((template) => {
            const conflicts = template.conflicts ?? {};
            const collides = Object.keys(conflicts).length > 0;
            return (
              <div key={template.name} className="rounded-xl border border-zinc-200/90 bg-white p-3.5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-sm font-semibold text-zinc-900">{template.name}</span>
                      {collides && (
                        <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800">
                          collides: {Object.keys(conflicts).join(', ')}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-zinc-500">{template.description}</p>
                    <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-zinc-400">
                      {Object.entries(template.counts ?? {}).map(([section, count]) =>
                        count ? (
                          <span key={section}>
                            {count} {section}
                          </span>
                        ) : null,
                      )}
                    </div>
                  </div>
                  <button
                    type="button"
                    disabled={readOnly || applyTemplate.isPending}
                    onClick={() => {
                      if (collides) {
                        setAnswer('');
                        setConfirming(template);
                      } else {
                        apply(template, false);
                      }
                    }}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-800 disabled:opacity-40"
                  >
                    {applyTemplate.isPending ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Sparkles className="h-3.5 w-3.5" />
                    )}
                    Apply
                  </button>
                </div>
                {collides && (
                  <div className="mt-2 space-y-0.5 text-xs text-zinc-500">
                    {Object.entries(conflicts).map(([section, names]) => (
                      <p key={section}>
                        existing {section}: <span className="font-mono">{names.join(', ')}</span>
                      </p>
                    ))}
                    <p>
                      will be {onConflict === 'skip' ? 'kept as they are' : 'updated'} — applying
                      needs a Y (yes) confirmation
                    </p>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {status && (
        <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          {status}
        </div>
      )}
      {error && (
        <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {error}
        </div>
      )}
      {readOnly && (
        <p className="mt-3 text-xs text-zinc-500">
          Read-only mode: templates cannot be applied here. Run{' '}
          <span className="font-mono">hobees init --template &lt;name&gt;</span> in a terminal.
        </p>
      )}

      {confirming && (
        <DialogShell title={`Confirm template: ${confirming.name}`} onClose={() => setConfirming(null)}>
          <div className="space-y-3 px-5 py-4 text-xs text-zinc-600">
            <p>
              This blueprint creates{' '}
              {Object.values(confirming.counts ?? {}).reduce((sum, count) => sum + count, 0)} entries.
              {' '}
              {Object.keys(confirming.conflicts ?? {}).length} of them already exist and will be{' '}
              <strong>{onConflict === 'skip' ? 'left unchanged' : 'updated'}</strong>.
            </p>
            <ul className="space-y-1">
              {Object.entries(confirming.conflicts ?? {}).map(([section, names]) => (
                <li key={section}>
                  <span className="font-medium text-zinc-700">{section}</span>:{' '}
                  <span className="font-mono">{names.join(', ')}</span>
                </li>
              ))}
            </ul>
            <label className="flex items-center gap-2">
              <span className="font-medium text-zinc-700">Type Y (yes) to confirm</span>
              <input
                autoFocus
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                placeholder="Y"
                className="w-24 rounded-lg border border-zinc-200 px-2 py-1.5 font-mono focus:outline-none focus:border-zinc-400"
              />
            </label>
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirming(null)}
                className="rounded-lg border border-zinc-200 px-3 py-1.5 font-medium text-zinc-600 hover:bg-zinc-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => apply(confirming, true)}
                disabled={!confirmed || applyTemplate.isPending}
                className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3 py-1.5 font-medium text-white hover:bg-zinc-800 disabled:opacity-40"
              >
                {applyTemplate.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Check className="h-3.5 w-3.5" />
                )}
                Apply
              </button>
            </div>
          </div>
        </DialogShell>
      )}
    </div>
  );
}

/** Browser twin of `hobees detect-providers`: env-var and local-port scan on demand.
 *
 * Detection itself writes nothing — it reports candidates, the user picks, and only
 * the picked aliases are registered.
 */
function ProviderDetectionPanel({ readOnly }: { readOnly: boolean }) {
  const detect = useDetectProviders();
  const register = useRegisterDetectedProviders();
  const [candidates, setCandidates] = useState<DetectedProvider[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    if (readOnly) return;
    setError(null);
    setStatus(null);
    try {
      const res = await detect.mutateAsync();
      setCandidates(res.candidates);
      setPicked(res.candidates.filter((candidate) => !candidate.registered).map((candidate) => candidate.alias));
      setStatus(
        res.candidates.length === 0
          ? 'Nothing found: no provider API key in the environment and no local server answered.'
          : `Found ${res.candidates.length} provider(s)${res.first_launch ? ' (first launch)' : ''}. Pick the ones to register.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Detection failed');
    }
  };

  const registerSelected = async () => {
    if (readOnly || picked.length === 0) return;
    setError(null);
    try {
      const res = await register.mutateAsync(picked);
      setStatus(
        `Registered ${res.registered.length} provider(s)${res.registered.length ? `: ${res.registered.join(', ')}` : ''}` +
        (res.skipped.length ? ` · already registered, left as is: ${res.skipped.join(', ')}` : ''),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not register providers');
    }
  };

  const toggle = (alias: string) =>
    setPicked((prev) => (prev.includes(alias) ? prev.filter((item) => item !== alias) : [...prev, alias]));

  return (
    <div className="rounded-2xl border border-zinc-200/90 bg-white p-4 shadow-sm sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-zinc-900">Detect providers</h2>
          <p className="mt-1 max-w-2xl text-xs text-zinc-500">
            Scans the environment for API keys (OpenAI, Anthropic, Gemini, OpenRouter,
            DeepSeek) and probes the local server ports (Ollama, llama.cpp, LM Studio).
            Detection reports candidates only — nothing is saved until you pick them.
          </p>
        </div>
        <button
          type="button"
          onClick={run}
          disabled={readOnly || detect.isPending}
          className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-800 disabled:opacity-40"
        >
          {detect.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Search className="h-3.5 w-3.5" />
          )}
          Run detection
        </button>
      </div>

      {candidates.length > 0 ? (
        <ul className="mt-3 space-y-2">
          {candidates.map((candidate) => (
            <li
              key={candidate.alias}
              className="flex items-start justify-between gap-3 rounded-xl border border-zinc-200/90 bg-white px-3 py-2.5"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-semibold text-zinc-900">{candidate.alias}</span>
                  {candidate.registered && (
                    <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
                      already registered
                    </span>
                  )}
                </div>
                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-zinc-500">
                  <span className="font-mono">{candidate.source_label}</span>
                  <span>{candidate.provider_type}</span>
                  <span>key: {candidate.api_key_env}</span>
                  {candidate.default_model && <span>model: {candidate.default_model}</span>}
                </div>
              </div>
              <input
                type="checkbox"
                aria-label={`Register ${candidate.alias}`}
                checked={picked.includes(candidate.alias)}
                disabled={readOnly || candidate.registered}
                onChange={() => toggle(candidate.alias)}
              />
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-xs text-zinc-400">
          {status ?? 'Run detection to see what is available on this machine.'}
        </p>
      )}

      {status && candidates.length > 0 && (
        <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          {status}
        </div>
      )}
      {error && (
        <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {error}
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={registerSelected}
          disabled={readOnly || picked.length === 0 || register.isPending}
          className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-800 disabled:opacity-40"
        >
          {register.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Check className="h-3.5 w-3.5" />
          )}
          Register {picked.length} selected
        </button>
        {readOnly && (
          <span className="text-xs text-zinc-500">
            Read-only mode: detection and registration are disabled here. Use{' '}
            <span className="font-mono">hobees detect-providers</span> in a terminal.
          </span>
        )}
      </div>
    </div>
  );
}

/** Danger zone on the Studio page: the browser twin of `hobees reset`.
 *
 * Same two scopes as the headless command — the config files inside ~/.hobees,
 * plus generated output when **--all** is checked. Nothing is sent unless the user
 * answers Y(es); the endpoint rejects an unconfirmed request as well, so a stray
 * click cannot clear the slate.
 */
function ResetPanel({ readOnly }: { readOnly: boolean }) {
  const [includeArtifacts, setIncludeArtifacts] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [answer, setAnswer] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ResetResponse | null>(null);
  const { data: plan, isLoading } = useResetPlan({ include_artifacts: includeArtifacts });
  const resetSlate = useResetSlate();

  const targets = plan?.targets ?? [];
  const confirmed = ['y', 'yes'].includes(answer.trim().toLowerCase());

  const openConfirm = () => {
    setAnswer('');
    setError(null);
    setConfirmOpen(true);
  };

  const run = async () => {
    if (!confirmed || readOnly || resetSlate.isPending) return;
    setError(null);
    try {
      const res = await resetSlate.mutateAsync({
        include_artifacts: includeArtifacts,
        confirmed: true,
      });
      setResult(res);
      setConfirmOpen(false);
      setAnswer('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reset failed');
    }
  };

  return (
    <div className="rounded-2xl border border-zinc-200/90 bg-white p-4 shadow-sm sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-zinc-900">Reset</h2>
          <p className="mt-1 max-w-2xl text-xs text-zinc-500">
            Removes the env file, databases and config files hobees created inside{' '}
            <span className="font-mono">~/.hobees</span>. Variables you exported in your shell are
            not changed, and a database served outside that folder is not dropped.
          </p>
        </div>
        <label className="inline-flex cursor-pointer items-center gap-2 text-xs font-medium text-zinc-600">
          <input
            type="checkbox"
            checked={includeArtifacts}
            onChange={(e) => {
              setIncludeArtifacts(e.target.checked);
              setResult(null);
            }}
          />
          Also remove generated output (<span className="font-mono">--all</span>: artifacts, skills,
          scratchpad)
        </label>
      </div>

      {isLoading ? (
        <p className="mt-3 text-xs text-zinc-400">Checking what exists…</p>
      ) : targets.length === 0 ? (
        <p className="mt-3 text-xs text-zinc-500">Nothing to remove — the slate is already clean.</p>
      ) : (
        <ul className="mt-3 space-y-1.5 text-xs">
          {targets.map((target) => (
            <li key={target.path} className="flex items-start justify-between gap-3">
              <span className="min-w-0 break-all font-mono text-zinc-600">
                {target.label}: {target.path}
              </span>
              <span className="shrink-0 text-zinc-400">
                {target.kind === 'directory' ? `${target.entries} file(s), ` : ''}
                {formatBytes(target.size)}
              </span>
            </li>
          ))}
        </ul>
      )}

      {plan?.notes && plan.notes.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-zinc-500">
          {plan.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}

      {error && (
        <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          <p>{result.removed.length} path(s) removed.</p>
          {result.failed.length > 0 && (
            <ul className="mt-1 space-y-1 text-rose-700">
              {result.failed.map((failure) => (
                <li key={failure}>{failure}</li>
              ))}
            </ul>
          )}
          {result.restart_required && (
            <p className="mt-1 text-zinc-600">
              Restart the web app, or run <span className="font-mono">hobees init</span>, so the env
              file and schema are rebuilt.
            </p>
          )}
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={openConfirm}
          disabled={readOnly || targets.length === 0}
          className="inline-flex items-center gap-1.5 rounded-lg border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-100 disabled:opacity-40"
        >
          <AlertTriangle className="h-3.5 w-3.5" />
          Reset
        </button>
        {readOnly && (
          <span className="text-xs text-zinc-500">
            Read-only mode: reset is disabled. Use <span className="font-mono">hobees reset</span> in
            a terminal.
          </span>
        )}
      </div>

      {confirmOpen && (
        <DialogShell title="Confirm reset" onClose={() => setConfirmOpen(false)}>
          <div className="space-y-3 px-5 py-4 text-xs text-zinc-600">
            <p>
              {targets.length} path(s) in {plan?.config_dir ?? '~/.hobees'} will be removed
              {includeArtifacts ? ', including generated output' : ''}. This cannot be undone.
            </p>
            <ul className="max-h-48 space-y-1 overflow-y-auto">
              {targets.map((target) => (
                <li key={target.path} className="break-all font-mono text-zinc-500">
                  {target.path}
                </li>
              ))}
            </ul>
            <label className="flex items-center gap-2">
              <span className="font-medium text-zinc-700">Type Y (yes) to confirm</span>
              <input
                autoFocus
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                placeholder="Y"
                className="w-24 rounded-lg border border-zinc-200 px-2 py-1.5 font-mono focus:outline-none focus:border-zinc-400"
              />
            </label>
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmOpen(false)}
                className="rounded-lg border border-zinc-200 px-3 py-1.5 font-medium text-zinc-600 hover:bg-zinc-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={run}
                disabled={!confirmed || resetSlate.isPending}
                className="inline-flex items-center gap-1.5 rounded-lg bg-rose-600 px-3 py-1.5 font-medium text-white hover:bg-rose-700 disabled:opacity-40"
              >
                {resetSlate.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Trash2 className="h-3.5 w-3.5" />
                )}
                Reset
              </button>
            </div>
          </div>
        </DialogShell>
      )}
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
/** The model a form stores: what was chosen, otherwise what the provider reports - the same
    order ModelPicker displays and the API resolves, so a model visible on screen can never be
    missing from the row being saved. */

const detectedCache: Record<string, string[]> = {};

function pickModel(requested: string, provider: Provider | null, detected?: string[]): string {
  return (
    requested.trim() ||
    provider?.default_model ||
    provider?.assistant_model ||
    detected?.[0] ||
    provider?.available_models?.[0] ||
    ''
  );
}

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

  /* Whatever the picker shows must be the value the form holds. The select displays the
     first available model when the caller has none, so saving said "no model" and Test
     model stayed disabled while one looked chosen - models found by this probe live only
     here, so they have to be handed back to the form. */
  useEffect(() => {
    if (value) return;
    const shown = provider?.default_model ?? provider?.assistant_model ?? models[0] ?? '';
    if (shown) onChange(shown);
  }, [value, provider, models, onChange]);


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
          // Shared so the form can resolve what this probe found.
          detectedCache[key] = res.models;
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
  const [modelName, setModelName] = useState(initial?.model_name ?? '');
  const selectedProvider = providers.find((p) => p.id === providerId) ?? null;
  const model = pickModel(modelName, selectedProvider, selectedProvider ? detectedCache[selectedProvider.alias] : undefined);

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
    if (!model) {
      setErr(`Provider '${selectedProvider?.alias ?? providerId}' reports no model - detect models or type one.`);
      return;
    }
    try {
      await onSave(
        {
          name: name.trim(),
          role_description: roleDescription.trim(),
          system_prompt: systemPrompt,
          provider_id: providerId,
          model_name: model,
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
          <ModelPicker label="Model (auto-detected)" value={model} onChange={setModelName} provider={selectedProvider} />
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
  const [modelName, setModelName] = useState(initial?.supervisor_model_name ?? '');
  const selectedProvider = providers.find((p) => p.id === providerId) ?? null;
  const model = pickModel(modelName, selectedProvider, selectedProvider ? detectedCache[selectedProvider.alias] : undefined);

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
    if (!model) {
      setErr(`Provider '${selectedProvider?.alias ?? providerId}' reports no model - detect models or type one.`);
      return;
    }
    try {
      await onSave(
        {
          name: name.trim(),
          goal_description: goalDesc.trim() || null,
          supervisor_provider_id: providerId,
          supervisor_model_name: model,
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
            value={model}
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

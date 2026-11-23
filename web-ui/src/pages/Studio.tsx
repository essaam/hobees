import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Bot,
  Check,
  Code2,
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
  useCreateBee,
  useCreateHive,
  useCreateProvider,
  useDeleteBee,
  useDeleteHive,
  useDeleteProvider,
  useDeleteSkill,
  useHives,
  useImportConfigYaml,
  useProviders,
  useSaveLastSkill,
  useSkills,
  useTools,
  useUpdateBee,
  useUpdateHive,
  useUpdateProvider,
} from '../hooks/useApi';
import type { Bee, Hive, Provider, ToolSchema } from '../types';
import { cn, copyText, downloadText } from '../utils/helpers';

type StudioTab = 'hives' | 'bees' | 'providers' | 'skills';

export function Studio() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { readOnly } = useAppContext();

  const initialTab = (searchParams.get('tab') as StudioTab) || 'hives';
  const [tab, setTab] = useState<StudioTab>(
    ['hives', 'bees', 'providers', 'skills'].includes(initialTab) ? initialTab : 'hives',
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
    if (t && ['hives', 'bees', 'providers', 'skills'].includes(t)) {
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
          <h1 className="text-xl font-semibold tracking-tight text-zinc-900">Hive Studio</h1>
          <p className="mt-0.5 text-sm text-zinc-500">
            Configure Hives, Worker Bees, tool approval gates, Providers, and Skills.
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
                <option value="gemini">gemini</option>
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
          <div className="grid grid-cols-2 gap-3">
            <Field label="API Key Env Var">
              <input
                required
                value={apiKeyEnv}
                onChange={(e) => setApiKeyEnv(e.target.value)}
                placeholder="OPENAI_API_KEY or NONE"
                className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs"
              />
            </Field>
            <Field label="Default Model">
              <input
                value={defaultModel}
                onChange={(e) => setDefaultModel(e.target.value)}
                placeholder="gpt-4o-mini"
                className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs"
              />
            </Field>
          </div>
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
                onChange={(e) => setProviderId(Number(e.target.value))}
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
          <div className="grid grid-cols-3 gap-3">
            <Field label="Model">
              <input
                required
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
                placeholder="gpt-4o-mini"
                className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs"
              />
            </Field>
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
                onChange={(e) => setProviderId(Number(e.target.value))}
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
          <div className="grid grid-cols-2 gap-3">
            <Field label="Supervisor Model">
              <input
                required
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
                placeholder="gpt-4o"
                className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs"
              />
            </Field>
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
          </div>
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

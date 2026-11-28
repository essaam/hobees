import { useState } from 'react';
import {
  Archive,
  Database,
  Download,
  Edit3,
  FileText,
  Plus,
  Search,
  Trash2,
  X,
} from 'lucide-react';
import { api } from '../api/client';
import { useAppContext } from '../context/AppContext';
import {
  useArtifacts,
  useDeleteMemory,
  useMemories,
  useUpsertMemory,
} from '../hooks/useApi';
import type { ArtifactItem, MemoryItem } from '../types';
import { cn, formatBytes, formatRelativeTime } from '../utils/helpers';

export function Storage() {
  const { readOnly } = useAppContext();
  const [tab, setTab] = useState<'memory' | 'artifacts'>('memory');

  // Memory state
  const [namespace, setNamespace] = useState<string>('all');
  const [query, setQuery] = useState('');
  const [editingMemory, setEditingMemory] = useState<MemoryItem | 'new' | null>(null);

  const { data: memoryData, isLoading: memLoading } = useMemories({
    namespace,
    q: query.trim() || undefined,
  });
  const upsertMemory = useUpsertMemory();
  const deleteMemory = useDeleteMemory();

  // Artifacts state
  const [selectedHive, setSelectedHive] = useState('');
  const { data: artifactData, isLoading: artLoading } = useArtifacts(selectedHive || undefined);
  const [previewArtifact, setPreviewArtifact] = useState<ArtifactItem | null>(null);
  const [previewText, setPreviewText] = useState<string>('');
  const [previewLoading, setPreviewLoading] = useState(false);

  const memories = memoryData?.memories ?? [];
  const namespaces = memoryData?.namespaces ?? ['global'];
  const artifacts = artifactData?.artifacts ?? [];
  const artifactHives = artifactData?.hives ?? [];

  const openPreview = async (item: ArtifactItem) => {
    setPreviewArtifact(item);
    setPreviewLoading(true);
    try {
      const text = await api.fetchArtifactText(item.path, selectedHive || undefined);
      setPreviewText(text);
    } catch {
      setPreviewText('(Unable to preview this file as text. Use Download instead.)');
    } finally {
      setPreviewLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-zinc-900">
            Memory &amp; Artifacts
          </h1>
          <p className="mt-0.5 text-sm text-zinc-500">
            Inspect scoped memories and preview or download generated Hive outputs.
          </p>
        </div>

        <div className="inline-flex rounded-lg border border-zinc-200 bg-white p-0.5 text-xs font-medium">
          <button
            type="button"
            onClick={() => setTab('memory')}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 transition-colors',
              tab === 'memory' ? 'bg-zinc-900 text-white' : 'text-zinc-600 hover:text-zinc-900',
            )}
          >
            <Database className="h-3.5 w-3.5" />
            Scoped Memory
          </button>
          <button
            type="button"
            onClick={() => setTab('artifacts')}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 transition-colors',
              tab === 'artifacts' ? 'bg-zinc-900 text-white' : 'text-zinc-600 hover:text-zinc-900',
            )}
          >
            <Archive className="h-3.5 w-3.5" />
            Artifacts
          </button>
        </div>
      </div>

      {tab === 'memory' ? (
        <div className="space-y-4">
          {/* Controls */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <select
                value={namespace}
                onChange={(e) => setNamespace(e.target.value)}
                aria-label="Filter by namespace"
                className="rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 focus:border-amber-500 focus:outline-none"
              >
                <option value="all">All Namespaces</option>
                <option value="global">global</option>
                <option value="hive:">All Hives (hive:*)</option>
                <option value="bee:">All Bees (bee:*)</option>
                <option value="container:">All Containers (container:*)</option>
                {namespaces
                  .filter((ns) => ns !== 'global')
                  .map((ns) => (
                    <option key={ns} value={ns}>
                      {ns}
                    </option>
                  ))}
              </select>

              <div className="relative w-64">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-400" />
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search key or content..."
                  className="w-full rounded-lg border border-zinc-200 bg-white py-1.5 pl-8 pr-3 text-xs text-zinc-800 placeholder:text-zinc-400 focus:border-amber-500 focus:outline-none"
                />
              </div>
            </div>

            {!readOnly && (
              <button
                type="button"
                onClick={() => setEditingMemory('new')}
                className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-800"
              >
                <Plus className="h-3.5 w-3.5" />
                Add Memory
              </button>
            )}
          </div>

          {/* Table */}
          <div className="overflow-hidden rounded-2xl border border-zinc-200/90 bg-white shadow-sm">
            {memLoading ? (
              <div className="py-12 text-center text-xs text-zinc-400">Loading memories…</div>
            ) : memories.length === 0 ? (
              <div className="py-14 text-center">
                <Database className="mx-auto h-7 w-7 text-zinc-300" />
                <p className="mt-2 text-sm font-medium text-zinc-700">No memories found</p>
                <p className="mt-0.5 text-xs text-zinc-400">
                  Save shared facts across sessions under global, hive, or bee scopes.
                </p>
              </div>
            ) : (
              <div className="divide-y divide-zinc-100">
                {memories.map((m) => (
                  <div
                    key={m.id}
                    className="flex items-start justify-between gap-4 px-4 py-3.5 hover:bg-zinc-50/70"
                  >
                    <div className="min-w-0 space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="rounded bg-zinc-100 px-2 py-0.5 font-mono text-[11px] text-zinc-600">
                          {m.namespace}
                        </span>
                        <span className="font-mono text-xs font-semibold text-zinc-900">{m.key}</span>
                        <span className="text-[11px] text-zinc-400">
                          {formatRelativeTime(m.updated_at)}
                        </span>
                      </div>
                      <p className="whitespace-pre-wrap text-xs leading-relaxed text-zinc-600 line-clamp-3">
                        {m.content}
                      </p>
                    </div>
                    {!readOnly && (
                      <div className="flex shrink-0 items-center gap-1">
                        <button
                          type="button"
                          onClick={() => setEditingMemory(m)}
                          className="rounded-lg p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-800"
                          aria-label={`Edit ${m.key}`}
                        >
                          <Edit3 className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            if (window.confirm(`Delete memory "${m.namespace}/${m.key}"?`)) {
                              deleteMemory.mutate(m.id);
                            }
                          }}
                          className="rounded-lg p-1.5 text-zinc-400 hover:bg-rose-50 hover:text-rose-600"
                          aria-label={`Delete ${m.key}`}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <select
              value={selectedHive}
              onChange={(e) => {
                setSelectedHive(e.target.value);
                setPreviewArtifact(null);
              }}
              aria-label="Filter artifacts by hive"
              className="rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 focus:border-amber-500 focus:outline-none"
            >
              <option value="">All Hives</option>
              {artifactHives.map((h) => (
                <option key={h} value={h}>
                  {h}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
            {/* File List */}
            <div className="overflow-hidden rounded-2xl border border-zinc-200/90 bg-white shadow-sm lg:col-span-5">
              {artLoading ? (
                <div className="py-12 text-center text-xs text-zinc-400">Loading artifacts…</div>
              ) : artifacts.length === 0 ? (
                <div className="py-14 text-center">
                  <Archive className="mx-auto h-7 w-7 text-zinc-300" />
                  <p className="mt-2 text-sm font-medium text-zinc-700">No output artifacts</p>
                  <p className="mt-0.5 text-xs text-zinc-400">
                    Files written by Bees under <code className="rounded bg-zinc-100 px-1">artifacts/&lt;hive&gt;/output/</code> appear here.
                  </p>
                </div>
              ) : (
                <div className="divide-y divide-zinc-100 max-h-[540px] overflow-y-auto">
                  {artifacts.map((art) => (
                    <button
                      key={art.path}
                      type="button"
                      onClick={() => openPreview(art)}
                      className={cn(
                        'flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-zinc-50',
                        previewArtifact?.path === art.path && 'bg-amber-50/70',
                      )}
                    >
                      <div className="flex min-w-0 items-center gap-2.5">
                        <FileText className="h-4 w-4 shrink-0 text-zinc-400" />
                        <div className="min-w-0">
                          <p className="truncate font-mono text-xs font-medium text-zinc-800">
                            {art.name}
                          </p>
                          <p className="truncate font-mono text-[11px] text-zinc-400">
                            {art.path}
                          </p>
                        </div>
                      </div>
                      <span className="shrink-0 font-mono text-[11px] text-zinc-400">
                        {formatBytes(art.size)}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Preview Pane */}
            <div className="overflow-hidden rounded-2xl border border-zinc-200/90 bg-white shadow-sm lg:col-span-7">
              {!previewArtifact ? (
                <div className="flex h-64 items-center justify-center text-xs text-zinc-400">
                  Select an artifact to preview its contents.
                </div>
              ) : (
                <div className="flex h-full flex-col">
                  <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3">
                    <span className="truncate font-mono text-xs font-medium text-zinc-800">
                      {previewArtifact.path}
                    </span>
                    <a
                      href={api.artifactContentUrl(
                        previewArtifact.path,
                        selectedHive || undefined,
                        true,
                      )}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-2.5 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-50"
                    >
                      <Download className="h-3.5 w-3.5" />
                      Download
                    </a>
                  </div>
                  <div className="max-h-[480px] flex-1 overflow-auto p-4">
                    {previewLoading ? (
                      <p className="text-xs text-zinc-400">Loading preview…</p>
                    ) : (
                      <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-zinc-800">
                        {previewText}
                      </pre>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Memory Modal */}
      {editingMemory && (
        <MemoryDialog
          initial={editingMemory === 'new' ? null : editingMemory}
          namespaces={namespaces}
          saving={upsertMemory.isPending}
          onClose={() => setEditingMemory(null)}
          onSave={async (data) => {
            await upsertMemory.mutateAsync(data);
            setEditingMemory(null);
          }}
        />
      )}
    </div>
  );
}

function MemoryDialog({
  initial,
  namespaces,
  saving,
  onClose,
  onSave,
}: {
  initial: MemoryItem | null;
  namespaces: string[];
  saving: boolean;
  onClose: () => void;
  onSave: (data: { namespace: string; key: string; content: string }) => Promise<void>;
}) {
  const [ns, setNs] = useState(initial?.namespace ?? 'global');
  const [key, setKey] = useState(initial?.key ?? '');
  const [content, setContent] = useState(initial?.content ?? '');

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    await onSave({ namespace: ns.trim() || 'global', key: key.trim(), content });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/30 p-4 backdrop-blur-[1px]"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-zinc-100 px-5 py-4">
          <h2 className="text-sm font-semibold text-zinc-900">
            {initial ? 'Edit Memory' : 'Add Memory'}
          </h2>
          <button type="button" onClick={onClose} className="rounded-lg p-1 text-zinc-400 hover:bg-zinc-100">
            <X className="h-4 w-4" />
          </button>
        </div>
        <form onSubmit={submit}>
          <div className="space-y-3.5 p-5 text-sm">
            <label className="block space-y-1">
              <span className="text-xs font-medium text-zinc-600">Namespace</span>
              <input
                list="hobees-namespaces"
                required
                disabled={Boolean(initial)}
                value={ns}
                onChange={(e) => setNs(e.target.value)}
                placeholder="global | hive:<name> | bee:<name>"
                className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs disabled:bg-zinc-50"
              />
              <datalist id="hobees-namespaces">
                {namespaces.map((n) => (
                  <option key={n} value={n} />
                ))}
              </datalist>
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-zinc-600">Key</span>
              <input
                required
                disabled={Boolean(initial)}
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="coding-style"
                className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs disabled:bg-zinc-50"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-zinc-600">Content</span>
              <textarea
                required
                rows={6}
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="Persistent context to recall across runs..."
                className="w-full rounded-lg border border-zinc-200 px-3 py-2 text-sm"
              />
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
      </div>
    </div>
  );
}

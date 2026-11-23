import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { GitBranch, RefreshCw, Search, ShieldAlert } from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { useTraces } from '../hooks/useApi';
import {
  cn,
  formatDuration,
  formatRelativeTime,
  formatTokens,
  statusDotClass,
  statusLabel,
  statusPillClass,
} from '../utils/helpers';

const STATUS_FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'running', label: 'Running' },
  { id: 'awaiting_approval', label: 'Awaiting Approval' },
  { id: 'completed', label: 'Completed' },
  { id: 'failed', label: 'Failed' },
] as const;

export function Traces() {
  const navigate = useNavigate();
  const { selectedContainer } = useAppContext();

  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [search, setSearch] = useState('');

  const { data: traces = [], isLoading, isFetching, refetch } = useTraces({
    container: selectedContainer,
    status: statusFilter,
    q: search.trim() || undefined,
    limit: 100,
  });

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-zinc-900">Runs &amp; Traces</h1>
          <p className="mt-0.5 text-sm text-zinc-500">
            Inspect multi-agent execution trees, approval gates, and checkpoints across containers.
          </p>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-600 hover:bg-zinc-50"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', isFetching && 'animate-spin')} />
          Refresh
        </button>
      </div>

      {/* Filter Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex flex-wrap rounded-lg border border-zinc-200 bg-white p-0.5 text-xs font-medium">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setStatusFilter(f.id)}
              className={cn(
                'rounded-md px-2.5 py-1 transition-colors',
                statusFilter === f.id
                  ? 'bg-zinc-900 text-white'
                  : 'text-zinc-600 hover:text-zinc-900',
              )}
            >
              {f.label}
            </button>
          ))}
        </div>

        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search thread ID or goal..."
            className="w-full rounded-lg border border-zinc-200 bg-white py-1.5 pl-8 pr-3 text-sm text-zinc-800 placeholder:text-zinc-400 focus:border-amber-500 focus:outline-none"
          />
        </div>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-2xl border border-zinc-200/90 bg-white shadow-sm">
        {isLoading ? (
          <div className="py-16 text-center text-sm text-zinc-400">Loading traces…</div>
        ) : traces.length === 0 ? (
          <div className="py-16 text-center">
            <GitBranch className="mx-auto h-8 w-8 text-zinc-300" />
            <p className="mt-3 text-sm font-medium text-zinc-700">No runs found</p>
            <p className="mt-1 text-xs text-zinc-500">
              Start a run from the Workbench or execute <code className="rounded bg-zinc-100 px-1.5 py-0.5">hobees run</code>.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-zinc-100 bg-zinc-50/60 text-xs font-medium text-zinc-500">
                  <th className="px-4 py-3">Thread / Goal</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="hidden md:table-cell px-4 py-3">Container</th>
                  <th className="hidden lg:table-cell px-4 py-3">Target</th>
                  <th className="hidden sm:table-cell px-4 py-3 text-right">Tokens</th>
                  <th className="hidden sm:table-cell px-4 py-3 text-right">Duration</th>
                  <th className="px-4 py-3 text-right">Started</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {traces.map((t) => (
                  <tr
                    key={t.thread_id}
                    onClick={() => navigate(`/traces/${encodeURIComponent(t.thread_id)}`)}
                    className="cursor-pointer transition-colors hover:bg-amber-50/40"
                  >
                    <td className="px-4 py-3 max-w-md">
                      <div className="flex items-center gap-2">
                        <span className={cn('h-2 w-2 shrink-0 rounded-full', statusDotClass(t.status))} />
                        <span className="truncate font-medium text-zinc-900">
                          {t.goal || '(no prompt)'}
                        </span>
                      </div>
                      <p className="mt-0.5 truncate pl-4 font-mono text-[11px] text-zinc-400">
                        {t.thread_id}
                      </p>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span
                        className={cn(
                          'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium',
                          statusPillClass(t.status),
                        )}
                      >
                        {t.pending_approvals > 0 && <ShieldAlert className="h-3 w-3" />}
                        {statusLabel(t.status)}
                      </span>
                    </td>
                    <td className="hidden md:table-cell px-4 py-3 font-mono text-xs text-zinc-600">
                      {t.container}
                    </td>
                    <td className="hidden lg:table-cell px-4 py-3 text-xs text-zinc-600">
                      {t.hive_name ?? t.entity_name}
                    </td>
                    <td className="hidden sm:table-cell px-4 py-3 text-right font-mono text-xs text-zinc-600">
                      {formatTokens(t.total_tokens)}
                    </td>
                    <td className="hidden sm:table-cell px-4 py-3 text-right font-mono text-xs text-zinc-600">
                      {formatDuration(t.duration_ms)}
                    </td>
                    <td className="px-4 py-3 text-right text-xs text-zinc-500 whitespace-nowrap">
                      {formatRelativeTime(t.started_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  Check,
  Clock,
  Code2,
  Copy,
  Download,
  GitBranch,
  History,
  Loader2,
  MessageSquare,
  Play,
  RotateCcw,
  ShieldAlert,
  Wrench,
} from 'lucide-react';
import { ApprovalActionCard } from '../components/ApprovalActionCard';
import { useAppContext } from '../context/AppContext';
import { useReplayTrace, useTrace } from '../hooks/useApi';
import type { ApprovalRecord, TraceNode } from '../types';
import {
  cn,
  copyText,
  downloadText,
  formatDuration,
  formatTokens,
  statusDotClass,
  statusLabel,
  statusPillClass,
} from '../utils/helpers';

type InspectorTab = 'messages' | 'tool' | 'checkpoint' | 'replay';

export function TraceExplorer() {
  const { threadId: rawThreadId } = useParams();
  const threadId = rawThreadId ? decodeURIComponent(rawThreadId) : undefined;
  const navigate = useNavigate();
  const { readOnly } = useAppContext();

  const { data: trace, isLoading, error, refetch } = useTrace(threadId);
  const replayMutation = useReplayTrace();

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<InspectorTab>('messages');
  const [copied, setCopied] = useState(false);

  // Replay controls
  const [patchMessage, setPatchMessage] = useState('');
  const [replayApprovalMode, setReplayApprovalMode] = useState<'interactive' | 'auto' | 'strict' | 'pause'>('interactive');
  const [replayNotice, setReplayNotice] = useState<string | null>(null);

  const selectedNode = useMemo<TraceNode | null>(() => {
    if (!trace || trace.nodes.length === 0) return null;
    return trace.nodes.find((n) => n.id === selectedNodeId) ?? trace.nodes[0];
  }, [trace, selectedNodeId]);

  useEffect(() => {
    if (trace && trace.nodes.length > 0 && !selectedNodeId) {
      // Focus pending approval node first if present, else first node
      const pendingNode = trace.nodes.find((n) =>
        n.approval_info.some((a) => a.decision === 'pending'),
      );
      if (pendingNode) {
        setSelectedNodeId(pendingNode.id);
        setActiveTab('tool');
      } else {
        setSelectedNodeId(trace.nodes[0].id);
      }
    }
  }, [trace, selectedNodeId]);

  const maxTokens = useMemo(() => {
    if (!trace) return 1;
    return Math.max(1, ...trace.nodes.map((n) => n.metrics?.total_tokens ?? 0));
  }, [trace]);

  const handleReplay = async () => {
    if (!trace || !selectedNode?.checkpoint_id) return;
    setReplayNotice(null);
    try {
      const res = await replayMutation.mutateAsync({
        threadId: trace.thread_id,
        request: {
          checkpoint_id: selectedNode.checkpoint_id,
          patch_message: patchMessage.trim() || undefined,
          approval_mode: replayApprovalMode,
        },
      });
      setReplayNotice(`Replay started from checkpoint ${res.forked_from.slice(0, 12)}.`);
      setPatchMessage('');
      refetch();
    } catch (err) {
      setReplayNotice(err instanceof Error ? err.message : 'Replay failed');
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-zinc-400">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading trace…
      </div>
    );
  }

  if (error || !trace) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-16 text-center">
        <p className="text-sm font-medium text-zinc-800">Trace not found</p>
        <p className="mt-1 text-xs text-zinc-500">
          {error instanceof Error ? error.message : 'Could not load this thread.'}
        </p>
        <button
          type="button"
          onClick={() => navigate('/traces')}
          className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to Runs &amp; Traces
        </button>
      </div>
    );
  }

  const pendingApprovals = trace.approvals.filter((a) => a.decision === 'pending');

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Top Summary Header */}
      <div className="shrink-0 border-b border-zinc-200/80 bg-white px-4 py-3.5 lg:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => navigate('/traces')}
                className="rounded-md p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
                aria-label="Back to traces"
              >
                <ArrowLeft className="h-4 w-4" />
              </button>
              <code className="truncate font-mono text-xs font-semibold text-zinc-900">
                {trace.thread_id}
              </code>
              <button
                type="button"
                onClick={() => {
                  copyText(trace.thread_id);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                }}
                className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
                aria-label="Copy thread ID"
              >
                {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
              </button>
              <span
                className={cn(
                  'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium',
                  statusPillClass(trace.status),
                )}
              >
                {statusLabel(trace.status)}
              </span>
            </div>

            <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 pl-7 text-xs text-zinc-500">
              <span>
                Container: <strong className="font-mono text-zinc-700">{trace.container}</strong>
              </span>
              <span>
                Target: <strong className="text-zinc-700">{trace.hive_name ?? trace.entity_name}</strong>
              </span>
              <span>
                Tokens: <strong className="font-mono text-zinc-700">{formatTokens(trace.total_tokens)}</strong>
              </span>
              <span>
                Latency: <strong className="font-mono text-zinc-700">{formatDuration(trace.total_latency_ms)}</strong>
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {!readOnly && (
              <button
                type="button"
                onClick={() => navigate(`/?thread=${encodeURIComponent(trace.thread_id)}`)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-800 transition-colors"
              >
                <Play className="h-3.5 w-3.5" />
                Continue Thread
              </button>
            )}
            <button
              type="button"
              onClick={() =>
                downloadText(
                  JSON.stringify(trace, null, 2),
                  `trace-${trace.thread_id.replace(/:/g, '__')}.json`,
                  'application/json',
                )
              }
              className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 transition-colors"
            >
              <Download className="h-3.5 w-3.5" />
              Export JSON
            </button>
          </div>
        </div>
      </div>

      {/* Split-Pane Explorer */}
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-12">
        {/* Left Pane: Chronological Execution Tree */}
        <div className="overflow-y-auto border-b border-zinc-200/80 bg-stone-50/50 p-4 lg:col-span-5 lg:border-b-0 lg:border-r">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
              Execution Tree ({trace.nodes.length})
            </h2>
            {pendingApprovals.length > 0 && (
              <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-700">
                <ShieldAlert className="h-3.5 w-3.5" />
                {pendingApprovals.length} paused
              </span>
            )}
          </div>

          {trace.nodes.length === 0 ? (
            <div className="rounded-xl border border-dashed border-zinc-200 bg-white p-8 text-center">
              <GitBranch className="mx-auto h-6 w-6 text-zinc-300" />
              <p className="mt-2 text-xs font-medium text-zinc-700">No step telemetry recorded yet</p>
              <p className="mt-1 text-xs text-zinc-400">
                Events appear here as the Hive delegates and executes tools.
              </p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {trace.nodes.map((node) => {
                const isSelected = selectedNode?.id === node.id;
                const isWorkerBranch =
                  node.node !== 'supervisor' && node.node !== 'system' && node.action_type !== 'final_output';
                const tok = node.metrics?.total_tokens ?? 0;
                const tokPct = tok > 0 ? Math.max(8, Math.round((tok / maxTokens) * 100)) : 0;

                return (
                  <button
                    key={node.id}
                    type="button"
                    onClick={() => {
                      setSelectedNodeId(node.id);
                      if (node.approval_info.length > 0 || node.tool_io) {
                        setActiveTab('tool');
                      }
                    }}
                    className={cn(
                      'w-full rounded-xl border p-3 text-left transition-all',
                      isWorkerBranch && 'ml-4 w-[calc(100%-1rem)]',
                      isSelected
                        ? 'border-amber-400 bg-white shadow-sm ring-1 ring-amber-400/30'
                        : 'border-zinc-200/80 bg-white/80 hover:border-zinc-300 hover:bg-white',
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className={cn('h-2 w-2 shrink-0 rounded-full', statusDotClass(node.status))} />
                        <span className="truncate text-xs font-semibold text-zinc-900">
                          {node.node}
                        </span>
                        {node.checkpoint_id && (
                          <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-500">
                            {node.checkpoint_id.slice(0, 8)}
                          </code>
                        )}
                      </div>
                      {node.metrics && (
                        <span className="shrink-0 font-mono text-[11px] text-zinc-400">
                          {formatTokens(node.metrics.total_tokens)} · {formatDuration(node.metrics.latency_ms)}
                        </span>
                      )}
                    </div>

                    <p className="mt-1 truncate pl-4 text-xs text-zinc-600">{node.payload_summary}</p>

                    {/* Gate Badges */}
                    {node.approval_info.map((gate) => (
                      <div
                        key={gate.id}
                        className="mt-2 ml-4 flex items-center justify-between rounded-lg border border-zinc-100 bg-zinc-50 px-2.5 py-1 text-[11px]"
                      >
                        <span className="font-mono text-zinc-600">
                          GATE · {gate.approval_mode}
                        </span>
                        <span className={cn('rounded-full px-2 py-0.5 font-medium', statusPillClass(gate.decision))}>
                          {statusLabel(gate.decision)}
                          {gate.wait_ms != null ? ` (${formatDuration(gate.wait_ms)})` : ''}
                        </span>
                      </div>
                    ))}

                    {/* Subtle Token Bar */}
                    {tokPct > 0 && (
                      <div className="mt-2 ml-4 h-1 w-28 overflow-hidden rounded-full bg-zinc-100">
                        <div
                          className="h-full rounded-full bg-amber-400"
                          style={{ width: `${tokPct}%` }}
                        />
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Right Pane: 4-Tab Step & Checkpoint Inspector */}
        <div className="flex min-h-0 flex-col bg-white lg:col-span-7">
          {/* Inspector Tabs */}
          <div className="flex shrink-0 items-center gap-1 border-b border-zinc-200/80 px-4 pt-2">
            {(
              [
                { id: 'messages', label: 'Handoff & Messages', icon: MessageSquare },
                { id: 'tool', label: 'Tool I/O & Gate', icon: Wrench },
                { id: 'checkpoint', label: 'Checkpoint State', icon: Code2 },
                { id: 'replay', label: 'Time-Travel Replay', icon: History },
              ] as const
            ).map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  'inline-flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-xs font-medium transition-colors',
                  activeTab === tab.id
                    ? 'border-amber-500 text-zinc-900'
                    : 'border-transparent text-zinc-500 hover:text-zinc-800',
                )}
              >
                <tab.icon className="h-3.5 w-3.5" />
                {tab.label}
              </button>
            ))}
          </div>

          {/* Tab Content */}
          <div className="flex-1 overflow-y-auto p-5">
            {!selectedNode ? (
              <div className="py-16 text-center text-xs text-zinc-400">
                Select a step on the left to inspect its details.
              </div>
            ) : activeTab === 'messages' ? (
              <div className="space-y-4">
                {trace.goal && (
                  <div className="rounded-xl border border-zinc-200/80 bg-zinc-50/70 p-4">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
                      Run Goal
                    </p>
                    <p className="mt-1.5 whitespace-pre-wrap text-sm text-zinc-800">{trace.goal}</p>
                  </div>
                )}

                {selectedNode.messages.length === 0 ? (
                  <p className="text-xs text-zinc-500">
                    No message text captured on this step ({selectedNode.action_type}).
                  </p>
                ) : (
                  selectedNode.messages.map((m, idx) => (
                    <div
                      key={idx}
                      className="rounded-xl border border-zinc-200/80 bg-white p-4 space-y-1.5"
                    >
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-semibold text-zinc-800">{m.label}</span>
                        <span className="font-mono text-[11px] text-zinc-400">{m.role}</span>
                      </div>
                      <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-zinc-700">
                        {m.content}
                      </pre>
                    </div>
                  ))
                )}

                {selectedNode.metrics && (
                  <div className="flex flex-wrap gap-4 rounded-xl border border-zinc-100 bg-zinc-50/60 px-4 py-3 text-xs text-zinc-600">
                    <span className="inline-flex items-center gap-1">
                      <Clock className="h-3.5 w-3.5 text-zinc-400" />
                      {formatDuration(selectedNode.metrics.latency_ms)}
                    </span>
                    <span>In: {formatTokens(selectedNode.metrics.input_tokens)}</span>
                    <span>Out: {formatTokens(selectedNode.metrics.output_tokens)}</span>
                    {selectedNode.metrics.model && (
                      <span className="font-mono text-zinc-500">{selectedNode.metrics.model}</span>
                    )}
                  </div>
                )}
              </div>
            ) : activeTab === 'tool' ? (
              <div className="space-y-5">
                {selectedNode.tool_io && (
                  <div className="rounded-xl border border-zinc-200/80 p-4 space-y-2">
                    <p className="text-xs font-semibold text-zinc-800">Tool Call Telemetry</p>
                    <pre className="overflow-x-auto rounded-lg bg-zinc-950 p-3 font-mono text-xs text-zinc-100">
                      {JSON.stringify(selectedNode.tool_io, null, 2)}
                    </pre>
                  </div>
                )}

                {selectedNode.approval_info.length === 0 ? (
                  !selectedNode.tool_io && (
                    <p className="text-xs text-zinc-500">
                      No tool calls or approval gates recorded for this step.
                    </p>
                  )
                ) : (
                  selectedNode.approval_info.map((gate) => (
                    <GateInspector key={gate.id} gate={gate} onResolved={() => refetch()} />
                  ))
                )}
              </div>
            ) : activeTab === 'checkpoint' ? (
              selectedNode.checkpoint_state ? (
                <pre className="overflow-x-auto rounded-xl bg-zinc-950 p-4 font-mono text-xs leading-relaxed text-zinc-100">
                  {JSON.stringify(selectedNode.checkpoint_state, null, 2)}
                </pre>
              ) : (
                <div className="rounded-xl border border-dashed border-zinc-200 p-8 text-center text-xs text-zinc-500">
                  No raw LangGraph checkpoint snapshot is attached to this step.
                </div>
              )
            ) : (
              <div className="max-w-lg space-y-4">
                <div className="rounded-xl border border-zinc-200 bg-zinc-50/70 p-4 text-xs text-zinc-600 space-y-1">
                  <p className="font-semibold text-zinc-800">Fork &amp; Replay from Checkpoint</p>
                  <p>
                    Selected checkpoint:{' '}
                    <code className="rounded bg-white px-1.5 py-0.5 font-mono text-zinc-800">
                      {selectedNode.checkpoint_id ?? 'none'}
                    </code>
                  </p>
                  <p className="text-zinc-500">
                    Re-executes from this checkpoint onward without re-running prior nodes, using current Bee prompts/models.
                  </p>
                </div>

                {!selectedNode.checkpoint_id ? (
                  <p className="text-xs text-amber-700">
                    Select a step with a checkpoint ID to enable time-travel replay.
                  </p>
                ) : readOnly ? (
                  <p className="text-xs text-zinc-500">
                    Time-travel replay is disabled in <span className="font-medium">--read-only</span> mode.
                  </p>
                ) : (
                  <>
                    <div>
                      <label className="mb-1.5 block text-xs font-medium text-zinc-700">
                        Patch Message (optional <code className="text-zinc-500">--patch-message</code>)
                      </label>
                      <textarea
                        value={patchMessage}
                        onChange={(e) => setPatchMessage(e.target.value)}
                        rows={3}
                        placeholder="Optional correction note injected into graph state before resuming..."
                        className="w-full rounded-lg border border-zinc-200 px-3 py-2 text-sm text-zinc-800 placeholder:text-zinc-400 focus:border-amber-500 focus:outline-none"
                      />
                    </div>

                    <div>
                      <label className="mb-1.5 block text-xs font-medium text-zinc-700">
                        Approval Mode Override
                      </label>
                      <select
                        value={replayApprovalMode}
                        onChange={(e) =>
                          setReplayApprovalMode(e.target.value as typeof replayApprovalMode)
                        }
                        className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs font-medium text-zinc-800 focus:border-amber-500 focus:outline-none"
                      >
                        <option value="interactive">interactive</option>
                        <option value="auto">auto</option>
                        <option value="strict">strict</option>
                        <option value="pause">pause</option>
                      </select>
                    </div>

                    <button
                      type="button"
                      disabled={replayMutation.isPending}
                      onClick={handleReplay}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-4 py-2 text-xs font-medium text-white hover:bg-zinc-800 disabled:opacity-50"
                    >
                      {replayMutation.isPending ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <RotateCcw className="h-3.5 w-3.5" />
                      )}
                      Replay from Checkpoint
                    </button>

                    {replayNotice && (
                      <p className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-xs text-zinc-700">
                        {replayNotice}
                      </p>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function GateInspector({
  gate,
  onResolved,
}: {
  gate: ApprovalRecord;
  onResolved: () => void;
}) {
  if (gate.decision === 'pending') {
    return <ApprovalActionCard approval={gate} onResolved={onResolved} />;
  }

  return (
    <div className="rounded-xl border border-zinc-200 p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold text-zinc-900">{gate.tool_name}</span>
          <span className="rounded bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-600">
            mode: {gate.approval_mode}
          </span>
        </div>
        <span className={cn('rounded-full px-2.5 py-0.5 text-xs font-medium', statusPillClass(gate.decision))}>
          {statusLabel(gate.decision)}
          {gate.wait_ms != null ? ` · ${formatDuration(gate.wait_ms)}` : ''}
        </span>
      </div>

      {gate.reason && (
        <p className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">
          Reason: {gate.reason}
        </p>
      )}

      {gate.decision === 'edit' && gate.final_args ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <p className="mb-1 text-[11px] font-medium text-zinc-500">Original Arguments</p>
            <pre className="overflow-x-auto rounded-lg border border-rose-200/60 bg-rose-950/95 p-3 font-mono text-xs text-rose-100">
              {JSON.stringify(gate.original_args, null, 2)}
            </pre>
          </div>
          <div>
            <p className="mb-1 text-[11px] font-medium text-zinc-500">Final Edited Arguments</p>
            <pre className="overflow-x-auto rounded-lg border border-emerald-200/60 bg-emerald-950/95 p-3 font-mono text-xs text-emerald-100">
              {JSON.stringify(gate.final_args, null, 2)}
            </pre>
          </div>
        </div>
      ) : (
        <div>
          <p className="mb-1 text-[11px] font-medium text-zinc-500">Arguments</p>
          <pre className="overflow-x-auto rounded-lg bg-zinc-950 p-3 font-mono text-xs text-zinc-100">
            {JSON.stringify(gate.original_args, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

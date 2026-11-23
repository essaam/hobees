import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  AlertCircle,
  ArrowRight,
  Bot,
  CheckCircle2,
  Copy,
  Loader2,
  Paperclip,
  Play,
  Square,
  Users,
  X,
  Zap,
} from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { useBees, useCreateRun, useHives } from '../hooks/useApi';
import type { TraceStreamEvent } from '../types';
import { cn, copyText, isMac } from '../utils/helpers';

interface AttachedFile {
  name: string;
  content: string;
}

export function Workbench() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { readOnly, selectedContainer } = useAppContext();

  const { data: hives = [] } = useHives();
  const { data: bees = [] } = useBees();
  const createRun = useCreateRun();

  const [scope, setScope] = useState<'hive' | 'bee' | 'assistant'>('hive');
  const [entityName, setEntityName] = useState('');
  const [approvalMode, setApprovalMode] = useState<'interactive' | 'auto' | 'strict' | 'pause'>('interactive');
  const [thinking, setThinking] = useState<'auto' | 'off' | 'low' | 'medium' | 'high'>('auto');
  const [prompt, setPrompt] = useState('');
  const [attachments, setAttachments] = useState<AttachedFile[]>([]);
  const [continueThreadId, setContinueThreadId] = useState<string | null>(
    () => searchParams.get('thread'),
  );

  const [isRunning, setIsRunning] = useState(false);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [events, setEvents] = useState<TraceStreamEvent[]>([]);
  const [finalOutput, setFinalOutput] = useState<string>('');
  const [runError, setRunError] = useState<string | null>(null);
  const [copiedThread, setCopiedThread] = useState(false);

  const esRef = useRef<EventSource | null>(null);
  const latestReplyRef = useRef<string>('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const entities = scope === 'hive' ? hives : scope === 'bee' ? bees : [];

  useEffect(() => {
    const threadParam = searchParams.get('thread');
    if (threadParam) {
      setContinueThreadId(threadParam);
      const parts = threadParam.split(':');
      if (parts.length === 4 && (parts[1] === 'hive' || parts[1] === 'bee' || parts[1] === 'assistant')) {
        setScope(parts[1]);
        if (parts[1] !== 'assistant') setEntityName(parts[2]);
      }
    }
  }, [searchParams]);

  useEffect(() => {
    if (scope === 'assistant') {
      setEntityName('default');
    } else if (entities.length > 0 && !entities.some((e) => e.name === entityName)) {
      setEntityName(entities[0].name);
    } else if (entities.length === 0) {
      setEntityName('');
    }
  }, [scope, entities, entityName]);

  useEffect(() => {
    return () => {
      esRef.current?.close();
    };
  }, []);

  const handleFiles = (files: FileList | null) => {
    if (!files) return;
    Array.from(files).forEach((file) => {
      const reader = new FileReader();
      reader.onload = (ev) => {
        const content = String(ev.target?.result ?? '');
        setAttachments((prev) => [...prev, { name: file.name, content }]);
      };
      reader.readAsText(file);
    });
  };

  const stopStream = () => {
    esRef.current?.close();
    esRef.current = null;
    setIsRunning(false);
  };

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (readOnly || isRunning) return;
    if (!prompt.trim() && attachments.length === 0) return;
    if (scope !== 'assistant' && !entityName) return;

    esRef.current?.close();
    setIsRunning(true);
    setEvents([]);
    setFinalOutput('');
    setRunError(null);
    latestReplyRef.current = '';

    let fullPrompt = prompt.trim();
    if (attachments.length > 0) {
      const block = attachments
        .map((f) => `\n### @${f.name}\n\`\`\`\n${f.content}\n\`\`\``)
        .join('\n');
      fullPrompt = `${fullPrompt}\n\n--- Attached Workspace Files ---${block}`;
    }

    try {
      const res = await createRun.mutateAsync({
        scope,
        entity_name: scope === 'assistant' ? 'default' : entityName,
        prompt: fullPrompt,
        thread_id: continueThreadId ?? undefined,
        container_name: selectedContainer !== 'all' ? selectedContainer : undefined,
        approval_mode: approvalMode,
        thinking: thinking === 'auto' ? undefined : thinking,
      });

      setActiveThreadId(res.thread_id);
      const es = new EventSource(`/api/v1/runs/${encodeURIComponent(res.thread_id)}/stream`);
      esRef.current = es;

      es.onmessage = (msg) => {
        try {
          const ev = JSON.parse(msg.data) as TraceStreamEvent;
          setEvents((prev) => [...prev, ev]);

          if (ev.event_type === 'SUPERVISOR_SYNTHESIS' || ev.event_type === 'BEE_REPLY') {
            const preview = String(ev.payload?.content_preview ?? '');
            if (preview) {
              latestReplyRef.current = preview;
              setFinalOutput(preview);
            }
          } else if (ev.event_type === 'HIVE_COMPLETE') {
            if (!latestReplyRef.current) {
              setFinalOutput('Completed.');
            }
            setIsRunning(false);
            es.close();
            esRef.current = null;
          } else if (ev.event_type === 'HIVE_ERROR') {
            const errMsg = String(
              ev.payload?.error ?? ev.payload?.error_preview ?? 'Execution failed',
            );
            setRunError(errMsg);
            setIsRunning(false);
            es.close();
            esRef.current = null;
          }
        } catch {
          // ignore malformed SSE chunks
        }
      };

      es.onerror = () => {
        setIsRunning(false);
        es.close();
        esRef.current = null;
      };
    } catch (err) {
      setRunError(err instanceof Error ? err.message : 'Failed to start run');
      setIsRunning(false);
    }
  };

  const canRun =
    !readOnly &&
    !isRunning &&
    (prompt.trim().length > 0 || attachments.length > 0) &&
    (scope === 'assistant' || Boolean(entityName));

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-zinc-900">Workbench</h1>
          <p className="mt-0.5 text-sm text-zinc-500">
            Run a Hive, Worker Bee, or Assistant and stream delegations and tool gates live.
          </p>
        </div>
        {continueThreadId && (
          <div className="inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs text-amber-900">
            <span>Continuing</span>
            <code className="max-w-[180px] truncate font-mono">{continueThreadId}</code>
            <button
              type="button"
              onClick={() => {
                setContinueThreadId(null);
                setSearchParams({});
              }}
              className="rounded-full p-0.5 hover:bg-amber-200/60"
              aria-label="Clear continued thread"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        )}
      </div>

      {/* Composer Card */}
      <form
        onSubmit={handleSubmit}
        className="overflow-hidden rounded-2xl border border-zinc-200/90 bg-white shadow-sm"
      >
        {/* Compact Controls Row */}
        <div className="flex flex-wrap items-center gap-2.5 border-b border-zinc-100 bg-zinc-50/50 px-4 py-3">
          {/* Scope segmented control */}
          <div className="inline-flex rounded-lg border border-zinc-200 bg-white p-0.5 text-xs font-medium">
            {(
              [
                { id: 'hive', label: 'Hive', icon: Users },
                { id: 'bee', label: 'Bee', icon: Bot },
                { id: 'assistant', label: 'Assistant', icon: Zap },
              ] as const
            ).map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => setScope(opt.id)}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 transition-colors',
                  scope === opt.id
                    ? 'bg-zinc-900 text-white'
                    : 'text-zinc-600 hover:text-zinc-900',
                )}
              >
                <opt.icon className="h-3.5 w-3.5" />
                {opt.label}
              </button>
            ))}
          </div>

          {/* Entity Picker */}
          {scope !== 'assistant' && (
            <select
              value={entityName}
              onChange={(e) => setEntityName(e.target.value)}
              disabled={entities.length === 0}
              aria-label="Select target"
              className="rounded-lg border border-zinc-200 bg-white px-2.5 py-1.5 text-xs font-medium text-zinc-800 focus:border-amber-500 focus:outline-none"
            >
              {entities.length === 0 ? (
                <option value="">No {scope}s configured</option>
              ) : (
                entities.map((e) => (
                  <option key={e.name} value={e.name}>
                    {e.name}
                  </option>
                ))
              )}
            </select>
          )}

          <div className="ml-auto flex flex-wrap items-center gap-2">
            <select
              value={approvalMode}
              onChange={(e) => setApprovalMode(e.target.value as typeof approvalMode)}
              aria-label="Approval mode"
              className="rounded-lg border border-zinc-200 bg-white px-2.5 py-1.5 text-xs text-zinc-700 focus:border-amber-500 focus:outline-none"
            >
              <option value="interactive">Approval: Interactive</option>
              <option value="auto">Approval: Auto</option>
              <option value="strict">Approval: Strict</option>
              <option value="pause">Approval: Pause</option>
            </select>

            <select
              value={thinking}
              onChange={(e) => setThinking(e.target.value as typeof thinking)}
              aria-label="Thinking level"
              className="rounded-lg border border-zinc-200 bg-white px-2.5 py-1.5 text-xs text-zinc-700 focus:border-amber-500 focus:outline-none"
            >
              <option value="auto">Thinking: Auto</option>
              <option value="off">Thinking: Off</option>
              <option value="low">Thinking: Low</option>
              <option value="medium">Thinking: Medium</option>
              <option value="high">Thinking: High</option>
            </select>
          </div>
        </div>

        {/* Prompt Textarea */}
        <div className="p-4">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && canRun) {
                e.preventDefault();
                handleSubmit();
              }
            }}
            disabled={readOnly || isRunning}
            rows={4}
            placeholder={
              readOnly
                ? 'Workbench execution is disabled in --read-only mode.'
                : scope === 'assistant'
                  ? 'Ask the Assistant anything...'
                  : `Describe the goal for ${entityName || scope}...`
            }
            className="w-full resize-none bg-transparent text-sm text-zinc-900 placeholder:text-zinc-400 focus:outline-none"
          />

          {/* Attached File Chips */}
          {attachments.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {attachments.map((att, idx) => (
                <span
                  key={`${att.name}-${idx}`}
                  className="inline-flex items-center gap-1.5 rounded-md border border-zinc-200 bg-zinc-50 px-2 py-1 font-mono text-xs text-zinc-700"
                >
                  @{att.name}
                  <button
                    type="button"
                    onClick={() => setAttachments((prev) => prev.filter((_, i) => i !== idx))}
                    className="text-zinc-400 hover:text-zinc-700"
                    aria-label={`Remove ${att.name}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Bottom Action Bar */}
        <div className="flex items-center justify-between border-t border-zinc-100 px-4 py-2.5">
          <div className="flex items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={(e) => {
                handleFiles(e.target.files);
                e.target.value = '';
              }}
            />
            <button
              type="button"
              disabled={readOnly || isRunning}
              onClick={() => fileInputRef.current?.click()}
              className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800 disabled:opacity-40 transition-colors"
            >
              <Paperclip className="h-3.5 w-3.5" />
              Attach @file
            </button>
            {scope !== 'assistant' && entities.length === 0 && (
              <button
                type="button"
                onClick={() => navigate(`/studio?tab=${scope === 'hive' ? 'hives' : 'bees'}`)}
                className="text-xs font-medium text-amber-700 hover:text-amber-800"
              >
                Create a {scope} in Hive Studio →
              </button>
            )}
          </div>

          <div className="flex items-center gap-2">
            <span className="hidden text-[11px] text-zinc-400 sm:inline">
              {isMac() ? '⌘Enter' : 'Ctrl+Enter'}
            </span>
            {isRunning ? (
              <button
                type="button"
                onClick={stopStream}
                className="inline-flex items-center gap-1.5 rounded-lg border border-rose-200 bg-rose-50 px-3.5 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-100 transition-colors"
              >
                <Square className="h-3 w-3 fill-current" />
                Disconnect
              </button>
            ) : (
              <button
                type="submit"
                disabled={!canRun}
                className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-4 py-1.5 text-xs font-medium text-white hover:bg-zinc-800 disabled:opacity-40 transition-colors"
              >
                <Play className="h-3.5 w-3.5" />
                Run
              </button>
            )}
          </div>
        </div>
      </form>

      {/* Live Execution Feed & Result */}
      {(activeThreadId || runError || events.length > 0) && (
        <section className="overflow-hidden rounded-2xl border border-zinc-200/90 bg-white shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-100 px-4 py-3">
            <div className="flex items-center gap-2">
              {isRunning ? (
                <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
              ) : runError ? (
                <AlertCircle className="h-4 w-4 text-rose-600" />
              ) : (
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
              )}
              <span className="text-xs font-semibold text-zinc-800">
                {isRunning ? 'Running' : runError ? 'Failed' : 'Completed'}
              </span>
              {activeThreadId && (
                <button
                  type="button"
                  onClick={() => {
                    copyText(activeThreadId);
                    setCopiedThread(true);
                    setTimeout(() => setCopiedThread(false), 1500);
                  }}
                  className="inline-flex items-center gap-1 rounded bg-zinc-100 px-2 py-0.5 font-mono text-[11px] text-zinc-600 hover:bg-zinc-200"
                  title="Copy thread ID"
                >
                  {activeThreadId}
                  <Copy className="h-3 w-3" />
                  {copiedThread && <span className="text-emerald-600">copied</span>}
                </button>
              )}
            </div>

            {activeThreadId && (
              <button
                type="button"
                onClick={() => navigate(`/traces/${encodeURIComponent(activeThreadId)}`)}
                className="inline-flex items-center gap-1 text-xs font-medium text-amber-700 hover:text-amber-800"
              >
                Inspect Trace
                <ArrowRight className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          {runError && (
            <div className="border-b border-rose-100 bg-rose-50/70 px-4 py-3 font-mono text-xs text-rose-700 whitespace-pre-wrap">
              {runError}
            </div>
          )}

          {/* Compact Live Activity Log */}
          {events.length > 0 && (
            <div className="border-b border-zinc-100 bg-zinc-50/40 px-4 py-3 space-y-1.5 max-h-56 overflow-y-auto">
              {events.map((ev, idx) => (
                <div key={idx} className="flex items-start gap-2.5 text-xs">
                  <span className="w-28 shrink-0 font-mono text-[11px] text-zinc-400">
                    {ev.event_type}
                  </span>
                  <span className="font-medium text-zinc-700">
                    {ev.source}
                    {ev.target ? ` → ${ev.target}` : ''}
                  </span>
                  {Boolean(ev.payload?.subtask_preview || ev.payload?.tool_name) && (
                    <span className="truncate text-zinc-500">
                      {String(ev.payload?.tool_name ?? ev.payload?.subtask_preview)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Output Body */}
          {finalOutput && (
            <div className="p-5">
              <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-zinc-800">
                {finalOutput}
              </pre>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

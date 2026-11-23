import { useEffect, useState } from 'react';
import { Check, Edit3, Loader2, ShieldAlert, XCircle } from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { useResolveApproval } from '../hooks/useApi';
import type { ApprovalRecord } from '../types';
import { cn } from '../utils/helpers';

interface ApprovalActionCardProps {
  approval: ApprovalRecord;
  onResolved?: () => void;
}

export function ApprovalActionCard({ approval, onResolved }: ApprovalActionCardProps) {
  const { readOnly } = useAppContext();
  const resolveMutation = useResolveApproval();

  const [argsText, setArgsText] = useState(() =>
    JSON.stringify(approval.original_args ?? {}, null, 2),
  );
  const [reason, setReason] = useState('');
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    setArgsText(JSON.stringify(approval.original_args ?? {}, null, 2));
    setReason('');
    setJsonError(null);
    setSubmitError(null);
  }, [approval.id, approval.original_args]);

  const validateArgs = (): Record<string, unknown> | null => {
    try {
      const parsed = JSON.parse(argsText);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        setJsonError('Tool arguments must be a JSON object.');
        return null;
      }
      setJsonError(null);
      return parsed as Record<string, unknown>;
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : 'Invalid JSON');
      return null;
    }
  };

  const handleAction = async (action: 'approve' | 'edit' | 'reject') => {
    setSubmitError(null);
    let editedArgs: Record<string, unknown> | undefined;
    if (action === 'edit') {
      const parsed = validateArgs();
      if (!parsed) return;
      editedArgs = parsed;
    }

    try {
      await resolveMutation.mutateAsync({
        approvalId: approval.id,
        request: {
          action,
          args: editedArgs,
          reason: action === 'reject' ? reason.trim() || 'Rejected by operator.' : undefined,
        },
      });
      onResolved?.();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to resolve approval');
    }
  };

  const busy = resolveMutation.isPending;

  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/40 p-4 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-100 text-amber-700">
            <ShieldAlert className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm font-semibold text-zinc-900">{approval.tool_name}</span>
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800">
                {approval.approval_mode}
              </span>
            </div>
            <p className="text-xs text-zinc-500">
              Requested by <span className="font-medium text-zinc-700">{approval.bee_name}</span> ·{' '}
              <span className="font-mono">{approval.container_name}</span>
            </p>
          </div>
        </div>
      </div>

      <div>
        <label className="mb-1.5 block text-xs font-medium text-zinc-600">
          Tool Arguments (JSON — edit to use &ldquo;Save Edit &amp; Resume&rdquo;)
        </label>
        <textarea
          value={argsText}
          onChange={(e) => {
            setArgsText(e.target.value);
            if (jsonError) setJsonError(null);
          }}
          readOnly={readOnly || busy}
          spellCheck={false}
          rows={6}
          className={cn(
            'w-full rounded-lg border bg-white p-3 font-mono text-xs text-zinc-800 focus:outline-none focus:ring-2 focus:ring-amber-500/30',
            jsonError ? 'border-rose-300' : 'border-zinc-200',
          )}
        />
        {jsonError && <p className="mt-1 text-xs text-rose-600">{jsonError}</p>}
      </div>

      {!readOnly && (
        <div>
          <label className="mb-1.5 block text-xs font-medium text-zinc-600">
            Rejection Reason (optional)
          </label>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            disabled={busy}
            placeholder="Reason if rejecting this tool call..."
            className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-800 placeholder:text-zinc-400 focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-500/20"
          />
        </div>
      )}

      {submitError && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {submitError}
        </div>
      )}

      {readOnly ? (
        <p className="text-xs text-zinc-500">
          Approval actions are disabled in <span className="font-medium">--read-only</span> mode.
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button
            type="button"
            disabled={busy}
            onClick={() => handleAction('approve')}
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3.5 py-2 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50 transition-colors"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
            Approve &amp; Resume
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => handleAction('edit')}
            className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 px-3.5 py-2 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-50 transition-colors"
          >
            <Edit3 className="h-3.5 w-3.5" />
            Save Edit &amp; Resume
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => handleAction('reject')}
            className="inline-flex items-center gap-1.5 rounded-lg border border-rose-200 bg-white px-3.5 py-2 text-xs font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-50 transition-colors"
          >
            <XCircle className="h-3.5 w-3.5" />
            Reject &amp; Resume
          </button>
        </div>
      )}
    </div>
  );
}

import { ExternalLink, ShieldAlert, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAppContext } from '../context/AppContext';
import { cn, formatRelativeTime } from '../utils/helpers';
import { ApprovalActionCard } from './ApprovalActionCard';

export function ApprovalDrawer() {
  const {
    approvalDrawerOpen,
    closeApprovalDrawer,
    pendingApprovals,
    focusedApproval,
    setFocusedApproval,
  } = useAppContext();
  const navigate = useNavigate();

  if (!approvalDrawerOpen) return null;

  const active =
    pendingApprovals.find((a) => a.id === focusedApproval?.id) ??
    pendingApprovals[0] ??
    null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="fixed inset-0 bg-zinc-900/25 backdrop-blur-[1px]"
        onClick={closeApprovalDrawer}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Pending Approvals"
        className="relative z-10 flex h-full w-full max-w-lg flex-col border-l border-zinc-200 bg-white shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-zinc-200 px-5 py-4">
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-amber-600" />
            <h2 className="text-sm font-semibold text-zinc-900">
              Pending Approvals ({pendingApprovals.length})
            </h2>
          </div>
          <button
            type="button"
            onClick={closeApprovalDrawer}
            className="rounded-lg p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
            aria-label="Close approvals drawer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {pendingApprovals.length === 0 ? (
            <div className="py-16 text-center">
              <p className="text-sm font-medium text-zinc-700">All clear</p>
              <p className="mt-1 text-xs text-zinc-500">No threads are waiting for approval.</p>
            </div>
          ) : (
            <>
              {pendingApprovals.length > 1 && (
                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-zinc-500">Queue</p>
                  <div className="flex flex-col gap-1.5">
                    {pendingApprovals.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => setFocusedApproval(item)}
                        className={cn(
                          'flex items-center justify-between rounded-lg border px-3 py-2 text-left text-xs transition-colors',
                          active?.id === item.id
                            ? 'border-amber-300 bg-amber-50/70 text-zinc-900'
                            : 'border-zinc-200 bg-white text-zinc-600 hover:bg-zinc-50',
                        )}
                      >
                        <span className="truncate">
                          <span className="font-mono font-medium">{item.tool_name}</span>{' '}
                          <span className="text-zinc-400">· {item.bee_name}</span>
                        </span>
                        <span className="shrink-0 text-[11px] text-zinc-400">
                          {formatRelativeTime(item.requested_at)}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {active && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between text-xs text-zinc-500">
                    <span className="font-mono truncate max-w-[300px]" title={active.thread_id}>
                      {active.thread_id}
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                        closeApprovalDrawer();
                        navigate(`/traces/${encodeURIComponent(active.thread_id)}`);
                      }}
                      className="inline-flex shrink-0 items-center gap-1 font-medium text-amber-700 hover:text-amber-800"
                    >
                      Open Trace
                      <ExternalLink className="h-3 w-3" />
                    </button>
                  </div>

                  <ApprovalActionCard
                    approval={active}
                    onResolved={() => {
                      if (pendingApprovals.length <= 1) {
                        closeApprovalDrawer();
                      }
                    }}
                  />
                </div>
              )}
            </>
          )}
        </div>
      </aside>
    </div>
  );
}

import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  const diffSec = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (diffSec < 10) return 'just now';
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 7) return `${diffDay}d ago`;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const mins = Math.floor(ms / 60_000);
  const secs = Math.floor((ms % 60_000) / 1000);
  return `${mins}m ${secs}s`;
}

export function formatTokens(tokens: number): string {
  if (!tokens) return '0';
  if (tokens < 1000) return `${tokens}`;
  if (tokens < 1_000_000) return `${(tokens / 1000).toFixed(1)}k`;
  return `${(tokens / 1_000_000).toFixed(2)}M`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function statusDotClass(status: string): string {
  switch (status.toLowerCase()) {
    case 'completed':
    case 'success':
    case 'approve':
      return 'bg-emerald-500';
    case 'running':
      return 'bg-blue-500 animate-pulse';
    case 'awaiting_approval':
    case 'pending':
    case 'edited':
    case 'edit':
    case 'paused':
      return 'bg-amber-500';
    case 'failed':
    case 'error':
    case 'rejected':
    case 'reject':
      return 'bg-rose-500';
    default:
      return 'bg-zinc-400';
  }
}

export function statusPillClass(status: string): string {
  switch (status.toLowerCase()) {
    case 'completed':
    case 'success':
    case 'approve':
      return 'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200';
    case 'running':
      return 'bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-200';
    case 'awaiting_approval':
    case 'pending':
    case 'edited':
    case 'edit':
    case 'paused':
      return 'bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200';
    case 'failed':
    case 'error':
    case 'rejected':
    case 'reject':
      return 'bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-200';
    default:
      return 'bg-zinc-100 text-zinc-700 ring-1 ring-inset ring-zinc-200';
  }
}

export function statusLabel(status: string): string {
  switch (status.toLowerCase()) {
    case 'awaiting_approval':
      return 'Awaiting Approval';
    case 'completed':
      return 'Completed';
    case 'running':
      return 'Running';
    case 'failed':
      return 'Failed';
    case 'approve':
      return 'Approved';
    case 'edit':
    case 'edited':
      return 'Edited';
    case 'reject':
    case 'rejected':
      return 'Rejected';
    case 'pending':
      return 'Pending';
    default:
      return status.replace(/_/g, ' ');
  }
}

export function copyText(text: string): Promise<void> {
  return navigator.clipboard.writeText(text);
}

export function downloadText(content: string, filename: string, mime = 'text/plain'): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function isMac(): boolean {
  return typeof navigator !== 'undefined' && /Mac|iPhone|iPad/i.test(navigator.platform);
}

import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import {
  Bell,
  Database,
  GitBranch,
  Lock,
  Menu,
  Search,
  Sparkles,
  Wrench,
  X,
} from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { cn, isMac } from '../utils/helpers';
import { ApprovalDrawer } from './ApprovalDrawer';
import { CommandPalette } from './CommandPalette';
import { ContainerSelector } from './ContainerSelector';

const NAV_ITEMS = [
  { to: '/', label: 'Workbench', icon: Sparkles, end: true },
  { to: '/traces', label: 'Runs & Traces', icon: GitBranch, end: false },
  { to: '/studio', label: 'Studio', icon: Wrench, end: false },
  { to: '/storage', label: 'Memory & Artifacts', icon: Database, end: false },
] as const;

export function Layout() {
  const {
    status,
    readOnly,
    pendingApprovals,
    openApprovalDrawer,
    setCommandPaletteOpen,
  } = useAppContext();
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex h-screen overflow-hidden bg-stone-50">
      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-zinc-900/25 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Left Sidebar (4 core views) */}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 flex w-56 flex-col border-r border-zinc-200/80 bg-white transition-transform duration-150 lg:static lg:translate-x-0',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-14 items-center justify-between px-4 border-b border-zinc-100">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-amber-500 text-white shadow-sm">
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.2">
                <polygon points="12 2 20 7 20 17 12 22 4 17 4 7 12 2" />
              </svg>
            </div>
            <span className="text-base font-semibold tracking-tight text-zinc-900">hobees</span>
          </div>
          <button
            type="button"
            onClick={() => setMobileOpen(false)}
            className="rounded-md p-1 text-zinc-400 hover:bg-zinc-100 lg:hidden"
            aria-label="Close navigation"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 space-y-1 p-3" aria-label="Main navigation">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              onClick={() => setMobileOpen(false)}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-amber-50 text-amber-900'
                    : 'text-zinc-600 hover:bg-zinc-100/80 hover:text-zinc-900',
                )
              }
            >
              {({ isActive }) => (
                <>
                  <item.icon
                    className={cn('h-4 w-4 shrink-0', isActive ? 'text-amber-600' : 'text-zinc-400')}
                  />
                  <span>{item.label}</span>
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Minimal status footer */}
        <div className="border-t border-zinc-100 px-4 py-3 text-xs text-zinc-500">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                'h-2 w-2 rounded-full',
                status?.status === 'ok' ? 'bg-emerald-500' : 'bg-zinc-300',
              )}
            />
            <span className="capitalize">{status?.database ?? 'connecting'}</span>
            {status?.version && (
              <span className="ml-auto font-mono text-[11px] text-zinc-400">v{status.version}</span>
            )}
          </div>
          {readOnly && (
            <div className="mt-2 inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800 ring-1 ring-inset ring-amber-200">
              <Lock className="h-3 w-3" />
              Read-only mode
            </div>
          )}
        </div>
      </aside>

      {/* Main Column */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* Top Context Bar */}
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-zinc-200/80 bg-white px-4 lg:px-6">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-100 lg:hidden"
              aria-label="Open navigation"
            >
              <Menu className="h-5 w-5" />
            </button>
            <ContainerSelector />
          </div>

          <div className="flex items-center gap-2.5">
            {pendingApprovals.length > 0 && (
              <button
                type="button"
                onClick={() => openApprovalDrawer(pendingApprovals[0])}
                className="inline-flex items-center gap-2 rounded-full border border-amber-300 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-900 hover:bg-amber-100 transition-colors"
              >
                <Bell className="h-3.5 w-3.5 text-amber-600 animate-pulse" />
                <span>
                  {pendingApprovals.length} Pending Approval{pendingApprovals.length > 1 ? 's' : ''}
                </span>
              </button>
            )}

            <button
              type="button"
              onClick={() => setCommandPaletteOpen(true)}
              className="inline-flex items-center gap-2 rounded-lg border border-zinc-200 bg-zinc-50/70 px-3 py-1.5 text-xs text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800 transition-colors"
              aria-label="Open command palette"
            >
              <Search className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Command Palette</span>
              <kbd className="rounded border border-zinc-200 bg-white px-1.5 py-0.5 font-mono text-[10px] text-zinc-500">
                {isMac() ? '⌘K' : 'Ctrl+K'}
              </kbd>
            </button>
          </div>
        </header>

        {/* Scrollable Workspace */}
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>

      <CommandPalette />
      <ApprovalDrawer />
    </div>
  );
}

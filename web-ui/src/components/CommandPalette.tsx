import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Bot,
  Container,
  Database,
  FileCode2,
  GitBranch,
  Key,
  Layers,
  Play,
  Search,
  Sparkles,
  Users,
} from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { useSaveLastSkill } from '../hooks/useApi';
import { cn, isMac } from '../utils/helpers';

interface PaletteAction {
  id: string;
  label: string;
  cli: string;
  category: string;
  icon: React.ReactNode;
  run: () => void;
  mutating?: boolean;
}

export function CommandPalette() {
  const { commandPaletteOpen, setCommandPaletteOpen, readOnly } = useAppContext();
  const navigate = useNavigate();
  const saveLastSkill = useSaveLastSkill();

  const [query, setQuery] = useState('');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const base = useMemo<PaletteAction[]>(
    () => [
      {
        id: 'workbench',
        label: 'Run a Goal (Workbench)',
        cli: '/goal <prompt>',
        category: 'Execute',
        icon: <Play className="h-4 w-4 text-amber-600" />,
        run: () => navigate('/'),
      },
      {
        id: 'create-hive',
        label: 'Create New Hive',
        cli: '/hive create',
        category: 'Studio',
        icon: <Users className="h-4 w-4 text-zinc-500" />,
        run: () => navigate('/studio?tab=hives&create=1'),
        mutating: true,
      },
      {
        id: 'create-bee',
        label: 'Create New Worker Bee',
        cli: '/bee create',
        category: 'Studio',
        icon: <Bot className="h-4 w-4 text-zinc-500" />,
        run: () => navigate('/studio?tab=bees&create=1'),
        mutating: true,
      },
      {
        id: 'add-provider',
        label: 'Register LLM Provider',
        cli: '/provider add',
        category: 'Studio',
        icon: <Key className="h-4 w-4 text-zinc-500" />,
        run: () => navigate('/studio?tab=providers&create=1'),
        mutating: true,
      },
      {
        id: 'save-skill',
        label: 'Save Last Run as Reusable Skill',
        cli: '/skill save-last',
        category: 'Studio',
        icon: <Sparkles className="h-4 w-4 text-zinc-500" />,
        run: () => {
          saveLastSkill.mutate(undefined, {
            onSuccess: () => navigate('/studio?tab=skills'),
          });
        },
        mutating: true,
      },
      {
        id: 'quick-setup',
        label: 'Quick setup (templates & reset)',
        cli: 'hobees init --template <name> | hobees reset',
        category: 'Studio',
        icon: <Layers className="h-4 w-4 text-zinc-500" />,
        run: () => navigate('/studio?tab=setup'),
      },
      {
        id: 'yaml-config',
        label: 'Export / Edit hobees.yaml',
        cli: 'hobees init --config ./hobees.yaml',
        category: 'Studio',
        icon: <FileCode2 className="h-4 w-4 text-zinc-500" />,
        run: () => navigate('/studio?mode=yaml'),
      },
      {
        id: 'containers',
        label: 'Container preparation (compose & Dockerfile)',
        cli: 'hobees web',
        category: 'Studio',
        icon: <Container className="h-4 w-4 text-zinc-500" />,
        run: () => navigate('/studio?tab=containers'),
      },
      {
        id: 'traces',
        label: 'Browse Runs & Traces',
        cli: 'hobees trace --list',
        category: 'Observe',
        icon: <GitBranch className="h-4 w-4 text-zinc-500" />,
        run: () => navigate('/traces'),
      },
      {
        id: 'storage',
        label: 'Browse Scoped Memory & Artifacts',
        cli: 'hobees memory list',
        category: 'Storage',
        icon: <Database className="h-4 w-4 text-zinc-500" />,
        run: () => navigate('/storage'),
      },
    ],
    [navigate, saveLastSkill],
  );

  const actions = useMemo<PaletteAction[]>(() => {
    return base.filter((a) => !readOnly || !a.mutating);
  }, [base, readOnly]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return actions;
    return actions.filter(
      (a) =>
        a.label.toLowerCase().includes(q) ||
        a.cli.toLowerCase().includes(q) ||
        a.category.toLowerCase().includes(q),
    );
  }, [actions, query]);

  // Single keydown path: the palette handles keys itself when focus is inside it
  // (input, row, or the dialog), and the window listener covers focus anywhere
  // else. The `defaultPrevented` guard keeps a key from being handled twice.
  const handleKey = useCallback(
    (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setCommandPaletteOpen(!commandPaletteOpen);
        return;
      }
      if (!commandPaletteOpen) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        setCommandPaletteOpen(false);
        return;
      }
      if (e.key === 'ArrowDown' && filtered.length > 0) {
        e.preventDefault();
        setSelectedIdx((i) => Math.min(i + 1, filtered.length - 1));
        return;
      }
      if (e.key === 'ArrowUp' && filtered.length > 0) {
        e.preventDefault();
        setSelectedIdx((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === 'Enter' && filtered[selectedIdx]) {
        e.preventDefault();
        filtered[selectedIdx].run();
        setCommandPaletteOpen(false);
      }
    },
    [commandPaletteOpen, setCommandPaletteOpen, filtered, selectedIdx],
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [handleKey]);

  useEffect(() => {
    if (commandPaletteOpen) {
      setQuery('');
      setSelectedIdx(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [commandPaletteOpen]);

  useEffect(() => {
    setSelectedIdx(0);
  }, [query]);

  // Keep the highlight inside the list when the filtered set shrinks.
  useEffect(() => {
    setSelectedIdx((i) => Math.min(i, Math.max(0, filtered.length - 1)));
  }, [filtered.length]);

  useEffect(() => {
    if (!commandPaletteOpen) return;
    const active = listRef.current?.querySelector('[data-active="true"]');
    if (active) active.scrollIntoView({ block: 'nearest' });
  }, [commandPaletteOpen, selectedIdx, filtered]);

  if (!commandPaletteOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-zinc-900/30 pt-[12vh] px-4 backdrop-blur-[2px]"
      onClick={() => setCommandPaletteOpen(false)}
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => handleKey(e.nativeEvent)}
      >
        <div className="flex items-center gap-3 border-b border-zinc-100 px-4 py-3">
          <Search className="h-4 w-4 text-zinc-400" />
          <input
            ref={inputRef}
            autoFocus
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search commands"
            role="combobox"
            aria-controls="command-palette-list"
            aria-expanded="true"
            aria-haspopup="listbox"
            aria-activedescendant={filtered.length > 0 ? `command-palette-option-${selectedIdx}` : undefined}
            placeholder="Search commands, CLI equivalents, or jump to a thread..."
            className="w-full bg-transparent text-sm text-zinc-900 placeholder:text-zinc-400 focus:outline-none"
          />
          <kbd className="rounded border border-zinc-200 bg-zinc-50 px-1.5 py-0.5 text-[11px] text-zinc-400">
            ESC
          </kbd>
        </div>

        <div
          ref={listRef}
          id="command-palette-list"
          role="listbox"
          aria-label="Command results"
          className="max-h-80 overflow-y-auto py-1.5"
        >
          {filtered.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-zinc-400">
              No matching commands
            </div>
          ) : (
            filtered.map((item, idx) => (
              <button
                key={item.id}
                id={`command-palette-option-${idx}`}
                role="option"
                aria-selected={idx === selectedIdx}
                data-active={idx === selectedIdx}
                type="button"
                onMouseEnter={() => setSelectedIdx(idx)}
                onClick={() => {
                  item.run();
                  setCommandPaletteOpen(false);
                }}
                className={cn(
                  'flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left transition-colors',
                  idx === selectedIdx ? 'bg-amber-50/80' : 'hover:bg-zinc-50',
                )}
              >
                <div className="flex min-w-0 items-center gap-3">
                  {item.icon}
                  <span className="truncate text-sm font-medium text-zinc-800">{item.label}</span>
                </div>
                <code className="max-w-[230px] shrink-0 truncate rounded bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-500">
                  {item.cli}
                </code>
              </button>
            ))
          )}
        </div>

        <div className="flex items-center justify-between border-t border-zinc-100 bg-zinc-50/70 px-4 py-2 text-[11px] text-zinc-400">
          <span>Type to filter · Enter to run</span>
          <span>{isMac() ? '⌘K' : 'Ctrl+K'} toggle</span>
        </div>
      </div>
    </div>
  );
}

import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, Globe, Server } from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { useContainers } from '../hooks/useApi';
import { cn } from '../utils/helpers';

export function ContainerSelector() {
  const { selectedContainer, setSelectedContainer } = useAppContext();
  const { data } = useContainers();
  const containers = data?.containers ?? [];

  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onOutside);
    return () => document.removeEventListener('mousedown', onOutside);
  }, []);

  const label = selectedContainer === 'all' ? 'All Containers' : selectedContainer;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-50 transition-colors"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {selectedContainer === 'all' ? (
          <Globe className="h-3.5 w-3.5 text-zinc-400" />
        ) : (
          <Server className="h-3.5 w-3.5 text-amber-600" />
        )}
        <span className="max-w-[180px] truncate">{label}</span>
        <ChevronDown className={cn('h-3.5 w-3.5 text-zinc-400 transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div
          role="listbox"
          className="absolute left-0 top-full z-50 mt-1.5 w-56 rounded-xl border border-zinc-200 bg-white py-1 shadow-lg"
        >
          <button
            type="button"
            role="option"
            aria-selected={selectedContainer === 'all'}
            onClick={() => {
              setSelectedContainer('all');
              setOpen(false);
            }}
            className={cn(
              'flex w-full items-center justify-between px-3 py-2 text-left text-sm transition-colors hover:bg-zinc-50',
              selectedContainer === 'all' && 'bg-amber-50/60 font-medium text-amber-900',
            )}
          >
            <span className="flex items-center gap-2">
              <Globe className="h-3.5 w-3.5 text-zinc-400" />
              All Containers
            </span>
            {selectedContainer === 'all' && <Check className="h-3.5 w-3.5 text-amber-600" />}
          </button>

          {containers.length > 0 && <div className="my-1 border-t border-zinc-100" />}

          {containers.map((name) => (
            <button
              key={name}
              type="button"
              role="option"
              aria-selected={selectedContainer === name}
              onClick={() => {
                setSelectedContainer(name);
                setOpen(false);
              }}
              className={cn(
                'flex w-full items-center justify-between px-3 py-2 text-left text-sm transition-colors hover:bg-zinc-50',
                selectedContainer === name && 'bg-amber-50/60 font-medium text-amber-900',
              )}
            >
              <span className="flex items-center gap-2 truncate font-mono text-xs">
                <Server className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
                <span className="truncate">{name}</span>
              </span>
              {selectedContainer === name && <Check className="h-3.5 w-3.5 shrink-0 text-amber-600" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

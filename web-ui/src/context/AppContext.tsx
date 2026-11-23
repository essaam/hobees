import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { usePendingApprovals, useStatus } from '../hooks/useApi';
import type { ApprovalRecord, StatusResponse, TraceStreamEvent } from '../types';
import { readStored, writeStored } from '../utils/storage';

export type WorkbenchScope = 'hive' | 'bee' | 'assistant';

/** Workbench pickers keyed by scope. Held in context (and persisted) so the
 * chosen provider survives navigation between views instead of snapping back to
 * the first entry in the list. */
export type WorkbenchSelections = Record<WorkbenchScope, string>;

/** Chosen model per provider alias, persisted so the assistant keeps the model
 * it was chatting with after the view or tab changes. */
export type WorkbenchModels = Record<string, string>;

/** The last Workbench state per scope: leaving the view and coming back shows
 * the same run (thread, activity feed, reply and prompt) instead of a blank page.
 * "New session" clears it. */
export interface WorkbenchSession {
  threadId: string | null;
  events: TraceStreamEvent[];
  output: string;
  error: string | null;
  running: boolean;
  prompt: string;
}

export type WorkbenchSessions = Record<WorkbenchScope, WorkbenchSession>;

const WORKBENCH_KEY = 'workbench';
/** Bound what the persisted session keeps so a long run cannot blow the storage quota. */
const MAX_SESSION_EVENTS = 200;

const DEFAULT_WORKBENCH: WorkbenchSelections = { assistant: '', hive: '', bee: '' };

const DEFAULT_SESSION: WorkbenchSession = {
  threadId: null,
  events: [],
  output: '',
  error: null,
  running: false,
  prompt: '',
};

const DEFAULT_SESSIONS: WorkbenchSessions = {
  assistant: { ...DEFAULT_SESSION },
  hive: { ...DEFAULT_SESSION },
  bee: { ...DEFAULT_SESSION },
};

interface WorkbenchState {
  scope: WorkbenchScope;
  selections: WorkbenchSelections;
  models: WorkbenchModels;
  sessions: WorkbenchSessions;
}

function loadWorkbench(): WorkbenchState {
  const raw = readStored<Partial<WorkbenchState>>(WORKBENCH_KEY, {
    scope: 'assistant',
    selections: DEFAULT_WORKBENCH,
    models: {},
    sessions: DEFAULT_SESSIONS,
  });
  const scope = raw?.scope ?? 'assistant';
  const sessions = { ...DEFAULT_SESSIONS, ...(raw?.sessions ?? {}) };
  return {
    scope: (['hive', 'bee', 'assistant'] as const).includes(scope) ? scope : 'assistant',
    selections: { ...DEFAULT_WORKBENCH, ...(raw?.selections ?? {}) },
    models: { ...(raw?.models ?? {}) },
    sessions: Object.fromEntries(
      (['hive', 'bee', 'assistant'] as const).map((key) => [
        key,
        { ...DEFAULT_SESSION, ...(sessions[key] ?? {}) },
      ]),
    ) as WorkbenchSessions,
  } as WorkbenchState;
}

interface AppContextValue {
  status: StatusResponse | undefined;
  readOnly: boolean;
  selectedContainer: string;
  setSelectedContainer: (container: string) => void;
  workbenchScope: WorkbenchScope;
  setWorkbenchScope: (scope: WorkbenchScope) => void;
  workbenchSelections: WorkbenchSelections;
  setWorkbenchSelection: (scope: WorkbenchScope, value: string) => void;
  workbenchModels: WorkbenchModels;
  setWorkbenchModel: (providerAlias: string, model: string) => void;
  workbenchSessions: WorkbenchSessions;
  updateWorkbenchSession: (scope: WorkbenchScope, patch: Partial<WorkbenchSession>) => void;
  appendWorkbenchEvent: (scope: WorkbenchScope, event: TraceStreamEvent) => void;
  newWorkbenchSession: (scope: WorkbenchScope) => void;
  pendingApprovals: ApprovalRecord[];
  commandPaletteOpen: boolean;
  setCommandPaletteOpen: (open: boolean) => void;
  approvalDrawerOpen: boolean;
  openApprovalDrawer: (approval?: ApprovalRecord) => void;
  closeApprovalDrawer: () => void;
  focusedApproval: ApprovalRecord | null;
  setFocusedApproval: (approval: ApprovalRecord | null) => void;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [selectedContainer, setSelectedContainer] = useState<string>('all');
  const [workbench, setWorkbench] = useState(loadWorkbench());
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [approvalDrawerOpen, setApprovalDrawerOpen] = useState(false);
  const [focusedApproval, setFocusedApproval] = useState<ApprovalRecord | null>(null);

  useEffect(() => {
    writeStored(WORKBENCH_KEY, workbench);
  }, [workbench]);

  const setWorkbenchScope = useCallback((scope: WorkbenchScope) => {
    setWorkbench((prev) => (prev.scope === scope ? prev : { ...prev, scope }));
  }, []);

  const setWorkbenchSelection = useCallback((scope: WorkbenchScope, value: string) => {
    setWorkbench((prev) =>
      prev.selections[scope] === value
        ? prev
        : { ...prev, selections: { ...prev.selections, [scope]: value } },
    );
  }, []);

  const setWorkbenchModel = useCallback((providerAlias: string, model: string) => {
    setWorkbench((prev) =>
      prev.models[providerAlias] === model
        ? prev
        : { ...prev, models: { ...prev.models, [providerAlias]: model } },
    );
  }, []);

  const updateWorkbenchSession = useCallback(
    (scope: WorkbenchScope, patch: Partial<WorkbenchSession>) => {
      setWorkbench((prev) => {
        const next: WorkbenchSession = { ...prev.sessions[scope], ...patch };
        if (next.events.length > MAX_SESSION_EVENTS) next.events = next.events.slice(-MAX_SESSION_EVENTS);
        return { ...prev, sessions: { ...prev.sessions, [scope]: next } };
      });
    },
    [],
  );

  const appendWorkbenchEvent = useCallback((scope: WorkbenchScope, event: TraceStreamEvent) => {
    setWorkbench((prev) => {
      const events = [...prev.sessions[scope].events, event].slice(-MAX_SESSION_EVENTS);
      return { ...prev, sessions: { ...prev.sessions, [scope]: { ...prev.sessions[scope], events } } };
    });
  }, []);

  const newWorkbenchSession = useCallback((scope: WorkbenchScope) => {
    setWorkbench((prev) => ({
      ...prev,
      sessions: { ...prev.sessions, [scope]: { ...DEFAULT_SESSION } },
    }));
  }, []);

  const { data: status } = useStatus();
  const { data: approvalsData } = usePendingApprovals(selectedContainer);
  const pendingApprovals = approvalsData?.approvals ?? [];

  const openApprovalDrawer = (approval?: ApprovalRecord) => {
    setFocusedApproval(approval ?? pendingApprovals[0] ?? null);
    setApprovalDrawerOpen(true);
  };

  const closeApprovalDrawer = () => {
    setApprovalDrawerOpen(false);
  };

  return (
    <AppContext.Provider
      value={{
        status,
        readOnly: Boolean(status?.read_only),
        selectedContainer,
        setSelectedContainer,
        workbenchScope: workbench.scope,
        setWorkbenchScope,
        workbenchSelections: workbench.selections,
        setWorkbenchSelection,
        workbenchModels: workbench.models,
        setWorkbenchModel,
        workbenchSessions: workbench.sessions,
        updateWorkbenchSession,
        appendWorkbenchEvent,
        newWorkbenchSession,
        pendingApprovals,
        commandPaletteOpen,
        setCommandPaletteOpen,
        approvalDrawerOpen,
        openApprovalDrawer,
        closeApprovalDrawer,
        focusedApproval,
        setFocusedApproval,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useAppContext(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useAppContext must be used inside AppProvider');
  return ctx;
}

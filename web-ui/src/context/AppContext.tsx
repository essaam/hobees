import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { usePendingApprovals, useStatus } from '../hooks/useApi';
import type { ApprovalRecord, StatusResponse } from '../types';
import { readStored, writeStored } from '../utils/storage';

export type WorkbenchScope = 'hive' | 'bee' | 'assistant';

/** Workbench pickers keyed by scope. Held in context (and persisted) so the
 * chosen provider/target survives navigation between views instead of snapping
 * back to the first entry in the list. */
export type WorkbenchSelections = Record<WorkbenchScope, string>;

/** Chosen model per provider alias, persisted so the assistant keeps the model
 * it was chatting with after the view or tab changes. */
export type WorkbenchModels = Record<string, string>;

const WORKBENCH_KEY = 'workbench';

const DEFAULT_WORKBENCH: WorkbenchSelections = { assistant: '', hive: '', bee: '' };

interface WorkbenchState {
  scope: WorkbenchScope;
  selections: WorkbenchSelections;
  models: WorkbenchModels;
}

function loadWorkbench(): WorkbenchState {
  const raw = readStored<Partial<WorkbenchState>>(WORKBENCH_KEY, {
    scope: 'assistant',
    selections: DEFAULT_WORKBENCH,
    models: {},
  });
  const scope = raw?.scope ?? 'assistant';
  return {
    scope: (['hive', 'bee', 'assistant'] as const).includes(scope) ? scope : 'assistant',
    selections: { ...DEFAULT_WORKBENCH, ...(raw?.selections ?? {}) },
    models: { ...(raw?.models ?? {}) },
  };
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

import { createContext, useContext, useState, type ReactNode } from 'react';
import { usePendingApprovals, useStatus } from '../hooks/useApi';
import type { ApprovalRecord, StatusResponse } from '../types';

interface AppContextValue {
  status: StatusResponse | undefined;
  readOnly: boolean;
  selectedContainer: string;
  setSelectedContainer: (container: string) => void;
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
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [approvalDrawerOpen, setApprovalDrawerOpen] = useState(false);
  const [focusedApproval, setFocusedApproval] = useState<ApprovalRecord | null>(null);

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

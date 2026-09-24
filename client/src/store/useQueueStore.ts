/**
 * UI state for the analyst incident queue. Server state lives in TanStack
 * Query — this store holds only selection/filters/drawer-visibility.
 */
import { create } from 'zustand';
import type { QueueFilters } from '@/services/api/v2Types';

interface QueueUIState {
  filters: QueueFilters;
  selectedIncidentId: string | null;
  drawerOpen: boolean;
  setFilters: (f: Partial<QueueFilters>) => void;
  resetFilters: () => void;
  selectIncident: (id: string | null) => void;
  setDrawerOpen: (open: boolean) => void;
}

const DEFAULT_FILTERS: QueueFilters = {
  status: 'needs_review',
  activity: 'all',
  minConfidence: null,
  timeRangeHours: null,
};

export const useQueueStore = create<QueueUIState>()((set) => ({
  filters: DEFAULT_FILTERS,
  selectedIncidentId: null,
  drawerOpen: false,
  setFilters: (f) => set((s) => ({ filters: { ...s.filters, ...f } })),
  resetFilters: () => set({ filters: DEFAULT_FILTERS }),
  selectIncident: (id) => set({ selectedIncidentId: id, drawerOpen: id !== null }),
  setDrawerOpen: (open) => set({ drawerOpen: open }),
}));

import { create } from 'zustand';

export type ViewMode = '2d' | '3d';
export type PanelKey = 'overview' | 'persistence' | 'alerts' | 'facilities' | 'agent' | 'predict' | 'model' | 'analytics';

interface UIState {
  viewMode: ViewMode; panel: PanelKey; autoRotate: boolean;
  focus: { lat: number; lon: number; ts: number } | null;
  setViewMode: (v: ViewMode) => void; setPanel: (p: PanelKey) => void;
  toggleAutoRotate: () => void; requestFocus: (lat: number, lon: number) => void;
}

export const useUIStore = create<UIState>()((set) => ({
  viewMode: '2d', panel: 'overview', autoRotate: true, focus: null,
  setViewMode: (viewMode) => set({ viewMode }),
  setPanel: (panel) => set({ panel }),
  toggleAutoRotate: () => set((s) => ({ autoRotate: !s.autoRotate })),
  requestFocus: (lat, lon) => set({ focus: { lat, lon, ts: Date.now() } }),
}));




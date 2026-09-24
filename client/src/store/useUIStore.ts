import { create } from 'zustand';

export type ViewMode = '2d' | '3d';
export type PanelKey = 'global-watch' | 'queue' | 'overview' | 'persistence' | 'alerts' | 'facilities' | 'agent' | 'predict' | 'model' | 'analytics' | 'history' | 'news';

/** Resizable-surface registry: [min, max, default] per key (Session 23). */
export const PANEL_CLAMP: Record<string, [number, number, number]> = {
  rightDock: [360, 640, 360],
  eventDrawer: [360, 720, 400],
  facilityDrawer: [360, 720, 400],
};
const LS_KEY = 'tw.panelSizes.v1';

function loadSizes(): Record<string, number> {
  if (typeof localStorage === 'undefined') return {}; // node tests / SSR safety
  try { return JSON.parse(localStorage.getItem(LS_KEY) ?? '{}') as Record<string, number>; }
  catch { return {}; }
}
function saveSizes(s: Record<string, number>): void {
  if (typeof localStorage === 'undefined') return;
  try { localStorage.setItem(LS_KEY, JSON.stringify(s)); } catch { /* private mode */ }
}
/** Current width for a resizable key (persisted or default). */
export function panelWidth(sizes: Record<string, number>, key: string): number {
  const d = PANEL_CLAMP[key] ?? [0, 0, 400];
  const w = sizes[key] ?? d[2];
  return Math.min(d[1], Math.max(d[0], w));
}

interface UIState {
  viewMode: ViewMode; panel: PanelKey; autoRotate: boolean;
  focus: { lat: number; lon: number; ts: number } | null;
  sceneEventId: string | null;
  setViewMode: (v: ViewMode) => void; setPanel: (p: PanelKey) => void;
  toggleAutoRotate: () => void; requestFocus: (lat: number, lon: number) => void;
    setSceneEventId: (id: string | null) => void;
  /** T13: 3D scene for ANY hotspot — one store flag, one dialog, every view. */
  openScene: (id: string) => void;
  closeScene: () => void;
  selfTest: boolean;
  toggleSelfTest: () => void;
  panelSizes: Record<string, number>;
  setPanelSize: (key: string, w: number) => void;
  resetPanelSize: (key: string) => void;
}

export const useUIStore = create<UIState>()((set) => ({
  viewMode: '2d', panel: 'global-watch', autoRotate: true, focus: null, sceneEventId: null,
  setViewMode: (viewMode) => set({ viewMode }),
  setPanel: (panel) => set({ panel }),
  toggleAutoRotate: () => set((s) => ({ autoRotate: !s.autoRotate })),
  requestFocus: (lat, lon) => set({ focus: { lat, lon, ts: Date.now() } }),
    setSceneEventId: (sceneEventId) => set({ sceneEventId }),
    openScene: (sceneEventId) => set({ sceneEventId }),
    closeScene: () => set({ sceneEventId: null }),
  selfTest: false,
  toggleSelfTest: () => set((s) => ({ selfTest: !s.selfTest })),
  panelSizes: loadSizes(),
  setPanelSize: (key, w) => set((s) => {
    const d = PANEL_CLAMP[key] ?? [0, 0, 400];
    const next = { ...s.panelSizes, [key]: Math.min(d[1], Math.max(d[0], Math.round(w))) };
    saveSizes(next);
    return { panelSizes: next };
  }),
  resetPanelSize: (key) => set((s) => {
    const next = { ...s.panelSizes, [key]: (PANEL_CLAMP[key] ?? [0, 0, 400])[2] };
    saveSizes(next);
    return { panelSizes: next };
  }),
}));




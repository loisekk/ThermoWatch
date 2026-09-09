import { create } from 'zustand';

export type BasemapMode = 'pending' | 'vector-110m' | 'canvas2d-fallback';

export interface MapApi { zoomIn: () => void; zoomOut: () => void; reset: () => void }

interface MapDiagState {
  mode: BasemapMode;
  ready: boolean;
  errors: string[];
  mapApi: MapApi | null;
  setMode: (m: BasemapMode) => void;
  setReady: (r: boolean) => void;
  pushError: (m: string) => void;
  setMapApi: (api: MapApi | null) => void;
  reset: () => void;
}

/** Visible map health + renderer-agnostic control API. A black viewport must never be silent. */
export const useMapDiagStore = create<MapDiagState>()((set) => ({
  mode: 'pending',
  ready: false,
  errors: [],
  mapApi: null,
  setMode: (mode) => set({ mode }),
  setReady: (ready) => set({ ready }),
  pushError: (m) => set((s) => ({ errors: [...s.errors.slice(-4), m] })),
  setMapApi: (mapApi) => set({ mapApi }),
  reset: () => set({ mode: 'pending', ready: false, errors: [], mapApi: null }),
}));


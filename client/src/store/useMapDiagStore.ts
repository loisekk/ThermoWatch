import { create } from 'zustand';
import type { RendererCapability, WebGLStatus } from '@/features/map2d/WebGLProbe';

export type BasemapMode = 'pending' | 'vector-110m' | 'canvas2d-fallback';

export interface MapApi {
  zoomIn: () => void;
  zoomOut: () => void;
  reset: () => void;
}

interface MapDiagState {
  mode: BasemapMode;
  ready: boolean;
  errors: string[];
  mapApi: MapApi | null;
  webgl: WebGLStatus | null;
  capability: RendererCapability | null;
  setMode: (m: BasemapMode) => void;
  setReady: (r: boolean) => void;
  pushError: (m: string) => void;
  setMapApi: (api: MapApi | null) => void;
  setWebGL: (w: WebGLStatus) => void;
  setCapability: (c: RendererCapability) => void;
  reset: () => void;
}

/** Visible map health + renderer-agnostic control API. A black viewport must never be silent. */
export const useMapDiagStore = create<MapDiagState>()((set) => ({
  mode: 'pending',
  ready: false,
  errors: [],
  mapApi: null,
  webgl: null,
  capability: null,
  setMode: (mode) => set({ mode }),
  setReady: (ready) => set({ ready }),
  pushError: (m) => set((s) => ({ errors: [...s.errors.slice(-4), m] })),
  setMapApi: (mapApi) => set({ mapApi }),
  setWebGL: (webgl) => set({ webgl }),
  setCapability: (capability) => set({ capability }),
  reset: () => set({ mode: 'pending', ready: false, errors: [], mapApi: null, webgl: null, capability: null }),
}));

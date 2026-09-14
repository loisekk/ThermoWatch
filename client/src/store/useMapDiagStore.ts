import { create } from 'zustand';
import type { RendererCapability, WebGLStatus } from '@/features/map2d/WebGLProbe';
import { GL_PIN_OK, type GLPin } from '@/features/scene/glSelfCheck';

export type BasemapMode = 'pending' | 'vector-110m' | 'canvas2d-fallback';

export interface MapApi {
  zoomIn: () => void;
  zoomOut: () => void;
  reset: () => void;
}

const GL_PIN_KEY = 'tw.glPin.v1';

/** T15: the GL pin is PERSISTED — a reload must never silently re-arm a context
 *  whose presenter paints white/black on this host. */
function loadGLPin(): GLPin {
  if (typeof localStorage === 'undefined') return GL_PIN_OK; // node tests / SSR safety
  try {
    const raw = localStorage.getItem(GL_PIN_KEY);
    if (!raw) return GL_PIN_OK;
    const p = JSON.parse(raw) as GLPin;
    return p && typeof p.pinned === 'boolean' ? p : GL_PIN_OK;
  } catch { return GL_PIN_OK; }
}

function saveGLPin(p: GLPin): void {
  if (typeof localStorage === 'undefined') return;
  try { localStorage.setItem(GL_PIN_KEY, JSON.stringify(p)); } catch { /* private mode */ }
}

interface MapDiagState {
  mode: BasemapMode;
  ready: boolean;
  errors: string[];
  mapApi: MapApi | null;
  webgl: WebGLStatus | null;
  capability: RendererCapability | null;
  glPin: GLPin;
  setMode: (m: BasemapMode) => void;
  setReady: (r: boolean) => void;
  pushError: (m: string) => void;
  setMapApi: (api: MapApi | null) => void;
  setWebGL: (w: WebGLStatus) => void;
  setCapability: (c: RendererCapability) => void;
  /** reason = pin persistently; null = clear (only after a passed frame-2 check). */
  setGlPin: (reason: string | null) => void;
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
  glPin: loadGLPin(),
  setMode: (mode) => set({ mode }),
  setReady: (ready) => set({ ready }),
  pushError: (m) => set((s) => ({ errors: [...s.errors.slice(-4), m] })),
  setMapApi: (mapApi) => set({ mapApi }),
  setWebGL: (webgl) => set({ webgl }),
  setCapability: (capability) => set({ capability }),
  setGlPin: (reason) => set((s) => {
    const glPin: GLPin = reason
      ? { pinned: true, reason, at: Date.now() }
      : GL_PIN_OK;
    saveGLPin(glPin);
    return { glPin };
  }),
  reset: () => set({ mode: 'pending', ready: false, errors: [], mapApi: null, webgl: null, capability: null }),
}));

import { create } from 'zustand';

export interface TimeRange { start: number; end: number; playing: boolean; speed: number }

export interface LayerVisibility {
  hexagonDensity: boolean;
  buildingExtrusion: boolean;
  spreadRings: boolean;
  timeSlider: boolean;
  persistentRings: boolean;
  facilities: boolean;
  graticule: boolean;
  labels: boolean;
  choropleth: boolean;
  nightTexture: boolean;
  imagery: boolean;
  starfield: boolean;
}

interface AnalyticsState {
  advancedMode: boolean;
  timeRange: TimeRange;
  windowKey: string;
  layers: LayerVisibility;
  duckdbReady: boolean;
    rendererOverride: 'auto' | 'maplibre' | 'canvas';
  globeOverride: 'auto' | 'gl' | 'canvas';
  setGlobeOverride: (g: 'auto' | 'gl' | 'canvas') => void;
  setAdvancedMode: (m: boolean) => void;
  setTimeRange: (r: Partial<TimeRange>) => void;
  setWindow: (key: string, hours: number | null) => void;
  setLayers: (l: Partial<LayerVisibility>) => void;
  setDuckDBReady: (r: boolean) => void;
  setRendererOverride: (r: 'auto' | 'maplibre' | 'canvas') => void;
  play: () => void;
  pause: () => void;
  resetTimeRange: () => void;
  /** Playback step: slides the window forward by 1 h × speed; wraps at "now". */
  tick: () => void;
}

/** Scrubber bounds: a fixed 14-day lookback ending at store-creation time. */
export const WINDOW_BOUNDS = (() => {
  const now = Date.now();
  return { min: now - 14 * 86_400_000, max: now };
})();
const STEP_MS = 3_600_000; // 1 h per tick
const DAY = 86_400_000;

export const useAnalyticsStore = create<AnalyticsState>()((set) => ({
  advancedMode: false,
  timeRange: { start: WINDOW_BOUNDS.min, end: WINDOW_BOUNDS.max, playing: false, speed: 1 },
  windowKey: '14d',
  layers: {
    hexagonDensity: true, buildingExtrusion: true, spreadRings: true, timeSlider: true,
    persistentRings: true, facilities: true, graticule: true, labels: true,
    choropleth: true, nightTexture: false, imagery: false, starfield: true,
  },
  duckdbReady: false,
  rendererOverride: 'auto',
  setAdvancedMode: (advancedMode) => set({ advancedMode }),
  setTimeRange: (r) => set((s) => ({ timeRange: { ...s.timeRange, ...r } })),
  setWindow: (key, hours) =>
    set({ windowKey: key, timeRange: { start: hours === null ? Date.now() - 365 * DAY : Date.now() - hours * 3_600_000, end: Date.now(), playing: false, speed: 1 } }),
  setLayers: (l) => set((s) => ({ layers: { ...s.layers, ...l } })),
  setDuckDBReady: (duckdbReady) => set({ duckdbReady }),
    setRendererOverride: (rendererOverride) => set({ rendererOverride }),
  globeOverride: 'auto',
  setGlobeOverride: (globeOverride) => set({ globeOverride }),
  play: () => set((s) => ({ timeRange: { ...s.timeRange, playing: true } })),
  pause: () => set((s) => ({ timeRange: { ...s.timeRange, playing: false } })),
  resetTimeRange: () =>
    set({ windowKey: '14d', timeRange: { start: WINDOW_BOUNDS.min, end: WINDOW_BOUNDS.max, playing: false, speed: 1 } }),
  tick: () =>
    set((s) => {
      if (!s.timeRange.playing) return {};
      const dur = s.timeRange.end - s.timeRange.start;
      const end = s.timeRange.end + STEP_MS * s.timeRange.speed;
      if (end < WINDOW_BOUNDS.max) return { timeRange: { ...s.timeRange, end } };
      // reached "now" — wrap back to the start of the lookback window
      return { timeRange: { ...s.timeRange, start: WINDOW_BOUNDS.min, end: WINDOW_BOUNDS.min + dur } };
    }),
}));


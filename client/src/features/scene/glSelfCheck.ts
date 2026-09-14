/** T10 GL self-check — pure helpers (vitest-node safe; no three import).
 *
 *  Doctrine: canvas-first, GL explicit opt-in, and a GL frame that presents
 *  uniform (black/white) or freezes can never stay on screen — the shell pins
 *  to Canvas2D with an honest chip instead. */

/** Variance across the RGBA byte sample. 0 = perfectly uniform raster. */
export function pixelVariance(px: Uint8Array): number {
  if (px.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < px.length; i++) sum += px[i];
  const mean = sum / px.length;
  let acc = 0;
  for (let i = 0; i < px.length; i++) {
    const d = px[i] - mean;
    acc += d * d;
  }
  return acc / px.length;
}

/** A real scene frame varies far above this; a wedged context reads uniform. */
export const UNIFORM_RASTER_VARIANCE = 1e-3;

export type SceneRenderer = 'webgl' | 'canvas';

/** Persisted GL pin (tw.glPin.v1) — survives reload, so a host whose presenter
 *  paints white/black can never silently re-arm the broken context. */
export interface GLPin { pinned: boolean; reason: string | null; at: number | null }
export const GL_PIN_OK: GLPin = { pinned: false, reason: null, at: null };

export interface SceneRendererOpts {
  /** probe verdict: capability (context creation alone lies) */
  cap: { rasterizes?: boolean } | null | undefined;
  /** user pressed "try GL" */
  forceGl: boolean;
  /** persisted pin (tw.glPin.v1) */
  pin: GLPin;
  /** one-shot retry armed by FORCE — consumes the pin only if frame-2 passes */
  retryArmed: boolean;
}

/** T15 resolution order: persisted pin → force-one-shot → capability.
 *  Canvas-first: GL only when the user explicitly forced it AND the probe proved
 *  rasterization AND the pin is not standing (or a one-shot retry is armed). */
export function resolveSceneRenderer(o: SceneRendererOpts): 'webgl' | 'canvas' {
  if (o.pin.pinned && !o.retryArmed) return 'canvas';
  if (o.forceGl && o.cap?.rasterizes === true) return 'webgl';
  return 'canvas';
}

/** Layout-safe mount gate: a zero-size container (dialog transition, hidden tab)
 *  must never reach renderer.setSize — a 0×0 buffer presents nothing forever. */
export const shouldRenderSize = (w: number, h: number): boolean =>
  Number.isFinite(w) && Number.isFinite(h) && w >= 10 && h >= 10;

/** T15 GL DIAG payload (scene-dialog diagnostic strip + copy report). */
export interface GLDiag {
  contextType: string;
  attributes: string;
  renderer: string;
  vendor: string;
  backingW: number;
  backingH: number;
  pixelRatio: number;
  frames: number;
  lastVariance: number | null;
  drawCalls: number;
  triangles: number;
}

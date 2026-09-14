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

export type SceneRenderer = 'webgl' | 'canvas2d';

export interface SceneRendererOpts {
  /** user pressed "try GL" */
  forced: boolean;
  /** probe verdict: capability?.rasterizes (context creation alone lies) */
  rasterizes: boolean | undefined;
  /** the pin ladder retired GL on this host */
  pinned: boolean;
}

/** Canvas-first routing: GL only when forced AND the probe proves rasterization
 *  AND the pin ladder has not retired GL. Everything else -> Canvas2D. */
export function resolveSceneRenderer(o: SceneRendererOpts): SceneRenderer {
  return o.forced && o.rasterizes === true && !o.pinned ? 'webgl' : 'canvas2d';
}

export const WORLD_W = 2000;
export const WORLD_H = 1000;

/** Scale (px per world unit) at which the world exactly COVERS the viewport — never letterboxed. */
export function coverScale(w: number, h: number): number {
  return Math.max(w / WORLD_W, h / WORLD_H);
}

/** Clamp pan so world edges can never enter the viewport. */
export function clampPan(ox: number, oy: number, base: number, w: number, h: number): { ox: number; oy: number } {
  const maxX = Math.max(0, (WORLD_W * base - w) / 2);
  const maxY = Math.max(0, (WORLD_H * base - h) / 2);
  return { ox: Math.min(maxX, Math.max(-maxX, ox)), oy: Math.min(maxY, Math.max(-maxY, oy)) };
}

/** MapLibre minZoom so 360° always spans at least the viewport (world fills screen).
 *  Guards: zero-size viewports and floating-point rounding are clamped so the
 *  constraint solver never sees -Infinity or a below-cover zoom. */
export function minZoomForCover(w: number, h: number): number {
  const z = Math.log2(Math.max(Math.max(1, w) / 256, Math.max(1, h) / 128));
  return Math.max(0.5, (Number.isFinite(z) ? z : 0.5) + 1e-9);
}

/** Pure tile-index range for a viewport — unit-testable. */
export function tileRange(tx: number, ty: number, cw: number, ch: number, size: number): { x0: number; x1: number; y0: number; y1: number } {
  return { x0: Math.floor(-tx / size), x1: Math.floor((cw - tx) / size), y0: Math.floor(-ty / size), y1: Math.floor((ch - ty) / size) };
}
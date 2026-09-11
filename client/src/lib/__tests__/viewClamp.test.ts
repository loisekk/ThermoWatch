import { describe, expect, it } from 'vitest';
import { clampPan, coverScale, minZoomForCover, tileRange, WORLD_W, WORLD_H } from '../geo/viewClamp';

describe('viewClamp', () => {
  it('coverScale fills the viewport (no letterbox)', () => {
    const s = coverScale(1600, 900);
    expect(WORLD_W * s).toBeGreaterThanOrEqual(1600);
    expect(WORLD_H * s).toBeGreaterThanOrEqual(900);
  });
  it('pan is clamped so edges never enter view', () => {
    const base = coverScale(1600, 900);
    const c = clampPan(99999, -99999, base, 1600, 900);
    expect(Math.abs(c.ox)).toBeLessThanOrEqual((WORLD_W * base - 1600) / 2 + 1e-9);
    expect(Math.abs(c.oy)).toBeLessThanOrEqual((WORLD_H * base - 900) / 2 + 1e-9);
  });
  it('minZoomForCover keeps 360° >= viewport', () => {
    const z = minZoomForCover(1600, 900);
    expect(256 * 2 ** z).toBeGreaterThanOrEqual(1600);
    expect(128 * 2 ** z).toBeGreaterThanOrEqual(900);
  });
  it('tileRange covers the viewport', () => {
    const r = tileRange(-100, -50, 800, 600, 256);
    expect(r.x1).toBeGreaterThan(r.x0);
    expect(r.y1).toBeGreaterThan(r.y0);
  });
});
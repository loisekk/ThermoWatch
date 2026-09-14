import { describe, expect, it } from 'vitest';
import { pixelVariance, resolveSceneRenderer, UNIFORM_RASTER_VARIANCE } from '../glSelfCheck';

describe('pixelVariance', () => {
  it('is exactly 0 for a perfectly uniform raster (black/white paint)', () => {
    expect(pixelVariance(new Uint8Array(32 * 32 * 4).fill(7))).toBe(0);
    expect(pixelVariance(new Uint8Array(32 * 32 * 4))).toBe(0);
    expect(pixelVariance(new Uint8Array(0))).toBe(0);
  });

  it('is far above the uniform threshold for real scene-like variation', () => {
    const px = new Uint8Array(64 * 4);
    for (let i = 0; i < 64; i++) {
      const v = i % 2 === 0 ? 0 : 255;
      px[i * 4] = v; px[i * 4 + 1] = v; px[i * 4 + 2] = v; px[i * 4 + 3] = 255;
    }
    expect(pixelVariance(px)).toBeGreaterThan(1000);
    expect(pixelVariance(px)).toBeGreaterThan(UNIFORM_RASTER_VARIANCE);
  });

  it('keeps single-byte noise under the threshold (no false pin)', () => {
    const px = new Uint8Array(1024 * 4).fill(10);
    px[500] = 11;
    expect(pixelVariance(px)).toBeLessThan(UNIFORM_RASTER_VARIANCE);
  });
});

describe('resolveSceneRenderer (T15 order: persisted pin → force-one-shot → capability)', () => {
  const PIN = { pinned: true, reason: 'uniform raster', at: 1 };
  const OK = { pinned: false, reason: null, at: null };

  it('persisted pin standing -> canvas (even forced + healthy)', () => {
    expect(resolveSceneRenderer({ cap: { rasterizes: true }, forceGl: true, pin: PIN, retryArmed: false })).toBe('canvas');
  });
  it('persisted pin + retry armed + forced + healthy -> webgl (one-shot)', () => {
    expect(resolveSceneRenderer({ cap: { rasterizes: true }, forceGl: true, pin: PIN, retryArmed: true })).toBe('webgl');
  });
  it('persisted pin + retry armed + broken probe -> canvas (probe still gates)', () => {
    expect(resolveSceneRenderer({ cap: { rasterizes: false }, forceGl: true, pin: PIN, retryArmed: true })).toBe('canvas');
  });
  it('no pin + forced + healthy -> webgl', () => {
    expect(resolveSceneRenderer({ cap: { rasterizes: true }, forceGl: true, pin: OK, retryArmed: false })).toBe('webgl');
  });
  it('no pin + forced + broken -> canvas (context creation alone lies)', () => {
    expect(resolveSceneRenderer({ cap: { rasterizes: false }, forceGl: true, pin: OK, retryArmed: false })).toBe('canvas');
  });
  it('no pin + missing verdict + forced -> canvas', () => {
    expect(resolveSceneRenderer({ cap: null, forceGl: true, pin: OK, retryArmed: false })).toBe('canvas');
  });
  it('default (not forced) -> canvas even with a healthy probe', () => {
    expect(resolveSceneRenderer({ cap: { rasterizes: true }, forceGl: false, pin: OK, retryArmed: false })).toBe('canvas');
  });
});

describe('shouldRenderSize (T15 layout-safe mount gate)', () => {
  it('rejects zero/near-zero and non-finite sizes', () => {
    expect(shouldRenderSize(0, 400)).toBe(false);
    expect(shouldRenderSize(400, 0)).toBe(false);
    expect(shouldRenderSize(9.9, 400)).toBe(false);
    expect(shouldRenderSize(400, 5)).toBe(false);
    expect(shouldRenderSize(Number.NaN, 400)).toBe(false);
    expect(shouldRenderSize(400, Number.POSITIVE_INFINITY)).toBe(false);
    expect(shouldRenderSize(-10, 400)).toBe(false);
  });
  it('accepts real sizes', () => {
    expect(shouldRenderSize(10, 10)).toBe(true);
    expect(shouldRenderSize(880, 600)).toBe(true);
  });
});

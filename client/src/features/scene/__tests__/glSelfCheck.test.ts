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

describe('resolveSceneRenderer (doctrine: canvas-first)', () => {
  it('forced + healthy probe -> webgl', () => {
    expect(resolveSceneRenderer({ forced: true, rasterizes: true, pinned: false })).toBe('webgl');
  });
  it('forced + broken probe -> canvas2d', () => {
    expect(resolveSceneRenderer({ forced: true, rasterizes: false, pinned: false })).toBe('canvas2d');
  });
  it('forced + missing probe verdict -> canvas2d (context creation alone lies)', () => {
    expect(resolveSceneRenderer({ forced: true, rasterizes: undefined, pinned: false })).toBe('canvas2d');
  });
  it('default (not forced) -> canvas2d even with a healthy probe', () => {
    expect(resolveSceneRenderer({ forced: false, rasterizes: true, pinned: false })).toBe('canvas2d');
  });
  it('pinned host -> canvas2d even when forced and healthy', () => {
    expect(resolveSceneRenderer({ forced: true, rasterizes: true, pinned: true })).toBe('canvas2d');
  });
});

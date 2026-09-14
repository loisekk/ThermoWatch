import { describe, expect, it } from 'vitest';
import { CARTO, LABEL_CAP, LEGEND, hexStr, scaleBarMeters } from '../cartography';

describe('cartography constants', () => {
  it('legend has palette-valid swatches and honest canopy line', () => {
    expect(LEGEND.length).toBeGreaterThanOrEqual(5);
    for (const l of LEGEND) expect(l.color).toMatch(/^#[0-9a-f]{6}$/);
    expect(LEGEND.some((l) => l.text.includes('illustrative'))).toBe(true);
  });

  it('hexStr renders 6-digit lowercase hex', () => {
    expect(hexStr(0x10141a)).toBe('#10141a');
    expect(hexStr(0x0a)).toBe('#00000a');
  });

  it('LABEL_CAP bounds label density', () => {
    expect(LABEL_CAP).toBeLessThanOrEqual(12);
  });
});

describe('scaleBarMeters', () => {
  it('picks 200 m when 200 m ≈ 120 px at the given geometry', () => {
    // fov 45°, height 1000 px, dist 20 units → mPerPx = 2·20·tan(22.5°)·100/1000 ≈ 1.657
    // → 200 m ≈ 120.7 px (closest to the 120 px target)
    expect(scaleBarMeters(20, 45, 1000)).toBe(200);
  });

  it('zooms in (smaller distance) → smaller round target', () => {
    const near = scaleBarMeters(6, 45, 1000);
    const far = scaleBarMeters(60, 45, 1000);
    expect(near).toBeLessThan(far);
    expect([50, 100, 200, 500, 1000, 2000]).toContain(near);
    expect([50, 100, 200, 500, 1000, 2000]).toContain(far);
  });

  it('ground palette stays dark (map-like, not wireframe-cage bright)', () => {
    expect(CARTO.ground).toBeLessThan(0x202830);
    expect(CARTO.gridOpacity).toBeLessThan(0.3);
  });
});

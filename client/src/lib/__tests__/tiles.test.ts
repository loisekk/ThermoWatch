import { describe, expect, it } from 'vitest';
import { mercatorLat, mercatorYFloat, visibleTiles } from '@/lib/geo/tiles';

describe('mercator lat/row round-trip', () => {
  it('row 0 top edge is the Web-Mercator latitude clamp', () => {
    expect(mercatorLat(0, 256)).toBeCloseTo(85.05112878, 3);
  });
  it('middle row is the equator', () => {
    expect(mercatorLat(128, 256)).toBeCloseTo(0, 6);
  });
  it('round-trips lat -> row -> lat', () => {
    for (const lat of [-60, -23.4, 0, 13.3, 45, 71.2]) {
      const n = 1024;
      expect(mercatorLat(mercatorYFloat(lat, n), n)).toBeCloseTo(lat, 4);
    }
  });
});

describe('visibleTiles', () => {
  it('full world at z=1 covers all four tiles', () => {
    const r = visibleTiles(-180, 180, -85, 85, 1);
    expect(r.x0).toBe(0); expect(r.x1).toBe(1);
    expect(r.y0).toBe(0); expect(r.y1).toBe(1);
  });
  it('India window at z=3 lands in the expected eastern/northern quadrant', () => {
    const r = visibleTiles(68, 97, 6, 37, 3);
    expect(r.x0).toBeGreaterThanOrEqual(4);
    expect(r.y0).toBeLessThanOrEqual(r.y1);
    expect(r.y0).toBeLessThan(4); // northern hemisphere rows
  });
});
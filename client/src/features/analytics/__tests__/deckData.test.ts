import { describe, expect, it } from 'vitest';
import {
  HAZARD_HEIGHTS, buildFacilityFootprints, buildSpreadRings, filterByTimeRange, generateCircle,
} from '@/features/analytics/deckData';
import type { FireEvent } from '@/types/domain';

function mk(id: string, frp: number, level: FireEvent['risk']['level'], lat = 22.5, lon = 78.0): FireEvent {
  return {
    id, lat, lon, frp, brightnessK: 330, confidence: 80, detectedAt: 1_750_000_000_000,
    satellite: 'VIIRS-SNPP', dayNight: 'N',
    classification: { primary: 'industrial', subtype: null, scores: { industrial: 1, persistent: 0, wildfire: 0, agricultural: 0 }, confidence: 80 },
    persistence: { consecutiveDays: 1, detections30d: 2, regime: 'transient' },
    risk: { score: level === 'critical' ? 90 : 60, level, drivers: [] },
    nearestFacilityId: null, facilityDistanceKm: null,
  };
}

describe('buildFacilityFootprints', () => {
  it('creates closed ~800 m square rings per facility', () => {
    const [fp] = buildFacilityFootprints([{ id: 'F-001', name: 'x', subtype: 'refinery', lat: 22.47, lon: 70.06, hazard: 'G-III' }]);
    expect(fp.polygon).toHaveLength(5);
    expect(fp.polygon[0]).toEqual(fp.polygon[4]); // closed ring
    const sideKm = (fp.polygon[2][1] - fp.polygon[1][1]) * 111; // full latitude span = 2δ
    expect(sideKm).toBeGreaterThan(0.7);
    expect(sideKm).toBeLessThan(0.9);
  });

  it('carries hazard for extrusion height lookup', () => {
    const [fp] = buildFacilityFootprints([{ id: 'F-001', name: 'x', subtype: 'refinery', lat: 22.47, lon: 70.06, hazard: 'G-III' }]);
    expect(HAZARD_HEIGHTS[fp.hazard]).toBe(2500);
  });
});

describe('buildSpreadRings', () => {
  it('only rings high/critical risk events', () => {
    const rings = buildSpreadRings([mk('low', 100, 'low'), mk('crit', 900, 'critical')]);
    expect(rings.every((r) => r.id.startsWith('crit-'))).toBe(true);
  });

  it('produces 6/12/24 h rings with growing radii and closed circles', () => {
    const rings = buildSpreadRings([mk('hi', 600, 'high')], [6, 12, 24]);
    expect(rings).toHaveLength(3);
    expect(rings.map((r) => r.hours)).toEqual([6, 12, 24]);
    for (const r of rings) {
      expect(r.polygon[0]).toEqual(r.polygon[r.polygon.length - 1]);
      expect(r.polygon).toHaveLength(33);
    }
  });
});

describe('generateCircle', () => {
  it('radius in degrees latitude matches the requested km', () => {
    const c = generateCircle(78, 22, 10);
    const dLat = c[8][1] - 22; // angle = pi/2 → pure north
    expect(dLat * 111).toBeCloseTo(10, 1);
  });
});

describe('filterByTimeRange', () => {
  it('is inclusive on both bounds', () => {
    const evts = [mk('a', 1, 'low'), mk('b', 1, 'low'), mk('c', 1, 'low')];
    evts[0].detectedAt = 1000;
    evts[1].detectedAt = 2000;
    evts[2].detectedAt = 3000;
    const out = filterByTimeRange(evts, 1000, 2000);
    expect(out.map((e) => e.id)).toEqual(['a', 'b']);
  });
});

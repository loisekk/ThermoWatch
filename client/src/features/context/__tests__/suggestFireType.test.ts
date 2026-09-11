import { describe, expect, it } from 'vitest';
import { suggestFireType } from '../suggestFireType';
import type { FireEvent, Facility } from '@/types/domain';

const FAC: Facility = { id: 'F-001', name: 'Jamnagar Refinery Complex', subtype: 'refinery', lat: 22.47, lon: 70.06, hazard: 'G-III' };

const mk = (over: Partial<FireEvent>): FireEvent =>
  ({
    id: 'TW-1', lat: 22.47, lon: 70.06, frp: 300, brightnessK: 350, confidence: 85,
    detectedAt: Date.parse('2026-10-15T00:00:00Z'), satellite: 'VIIRS-SNPP', dayNight: 'N',
    classification: { primary: 'persistent', subtype: 'refinery', scores: { industrial: 0.2, persistent: 0.6, wildfire: 0.1, agricultural: 0.1 }, confidence: 85 },
    persistence: { consecutiveDays: 12, detections30d: 26, regime: 'persistent' },
    risk: { score: 70, level: 'high', drivers: [] },
    nearestFacilityId: 'F-001', facilityDistanceKm: 0.4,
    ...over,
  }) as FireEvent;

describe('suggestFireType', () => {
  it('ranks chronic process heat first for a persistent flare-adjacent source', () => {
    const h = suggestFireType(mk({}), [FAC]);
    expect(h[0].label).toContain('Jamnagar');
    expect(h[0].evidence.length).toBeGreaterThan(0);
  });
  it('ranks vegetation fire first for a far, diurnal, forest-context event', () => {
    const h = suggestFireType(mk({
      nearestFacilityId: null, facilityDistanceKm: null,
      classification: { primary: 'wildfire', subtype: null, scores: { industrial: 0.05, persistent: 0.05, wildfire: 0.8, agricultural: 0.1 }, confidence: 80 },
      persistence: { consecutiveDays: 2, detections30d: 3, regime: 'transient' },
    }), [FAC]);
    expect(h[0].label).toBe('Vegetation / forest fire');
  });
  it('boosts residue-burn hypothesis inside the Kharif window', () => {
    const agri = { primary: 'agricultural' as const, subtype: null as null, scores: { industrial: 0.05, persistent: 0.05, wildfire: 0.15, agricultural: 0.75 }, confidence: 80 };
    const inWin = suggestFireType(mk({ classification: agri, detectedAt: Date.parse('2026-10-20T00:00:00Z'), nearestFacilityId: null, facilityDistanceKm: null }), [FAC]);
    const offWin = suggestFireType(mk({ classification: agri, detectedAt: Date.parse('2026-07-20T00:00:00Z'), nearestFacilityId: null, facilityDistanceKm: null }), [FAC]);
    const w = (h: ReturnType<typeof suggestFireType>) => h.find((x) => x.label.startsWith('Crop-residue'))?.weight ?? 0;
    expect(w(inWin)).toBeGreaterThan(w(offWin));
  });
});
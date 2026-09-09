import { describe, expect, it } from 'vitest';
import { COUNTRY_BOXES, COUNTRY_LABELS, countryCounts } from '@/lib/geo/countryIndex';
import type { FireEvent } from '@/types/domain';

const ev = (lat: number, lon: number): FireEvent =>
  ({
    id: 'x', lat, lon, frp: 10, brightnessK: 320, confidence: 70, detectedAt: Date.now(),
    satellite: 'VIIRS-SNPP', dayNight: 'D',
    classification: { primary: 'wildfire', subtype: null, scores: { industrial: 0, persistent: 0, wildfire: 1, agricultural: 0 }, confidence: 70 },
    persistence: { consecutiveDays: 1, detections30d: 1, regime: 'transient' },
    risk: { score: 10, level: 'low', drivers: [] },
    nearestFacilityId: null, facilityDistanceKm: null,
  }) as FireEvent;

describe('countryIndex', () => {
  it('indexes ~170+ countries with finite boxes', () => {
    expect(COUNTRY_BOXES.length).toBeGreaterThan(150);
    for (const b of COUNTRY_BOXES.slice(0, 20)) {
      expect(b.maxLon).toBeGreaterThanOrEqual(b.minLon);
      expect(b.maxLat).toBeGreaterThanOrEqual(b.minLat);
    }
  });
  it('bbox-joins an India event to India', () => {
    const counts = countryCounts([ev(22.5, 79.0)]);
    const hit = COUNTRY_BOXES.find((b) => counts.get(b.id));
    expect(hit?.name).toBe('India');
  });
  it('labels exclude Antarctica and cap at 26', () => {
    expect(COUNTRY_LABELS.length).toBeLessThanOrEqual(26);
    expect(COUNTRY_LABELS.some((l) => l.name === 'Antarctica')).toBe(false);
  });
});
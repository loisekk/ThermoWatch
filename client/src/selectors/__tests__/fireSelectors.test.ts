import { describe, expect, it } from 'vitest';
import { computeKpis, computeTimeline, filterEvents } from '@/selectors/fireSelectors';
import type { FireEvent } from '@/types/domain';

const DAY = 86_400_000;
const NOW = Date.now();

function mk(id: string, ageMs: number, primary: 'industrial' | 'persistent' | 'wildfire' | 'agricultural', conf = 80, regime: 'transient' | 'persistent' | 'seasonal' = 'transient', days = 1): FireEvent {
  return {
    id, lat: 20, lon: 78, frp: 100, brightnessK: 330, confidence: conf, detectedAt: NOW - ageMs,
    satellite: 'VIIRS-SNPP', dayNight: 'N',
    classification: { primary, subtype: null, scores: { industrial: 0.4, persistent: 0.3, wildfire: 0.2, agricultural: 0.1 }, confidence: conf },
    persistence: { consecutiveDays: days, detections30d: days * 2, regime },
    risk: { score: 50, level: 'moderate', drivers: [] },
    nearestFacilityId: null, facilityDistanceKm: null,
  } as FireEvent;
}

describe('computeKpis', () => {
  it('counts 24h window and delta vs previous 24h', () => {
    const k = computeKpis([mk('a', 1000, 'industrial'), mk('b', 2 * DAY, 'wildfire')], NOW);
    expect(k.active24).toBe(1);
    expect(k.delta24).toBe(0);
    expect(k.industrialShare).toBe(100);
  });
});

describe('filterEvents', () => {
  it('applies confidence floor and persistent-only', () => {
    const evts = [mk('a', 1, 'industrial', 90), mk('b', 1, 'persistent', 40, 'persistent', 9)];
    expect(filterEvents(evts, { classes: ['industrial', 'persistent'], minConfidence: 50, persistentOnly: false })).toHaveLength(1);
    expect(filterEvents(evts, { classes: ['industrial', 'persistent'], minConfidence: 0, persistentOnly: true })).toHaveLength(1);
  });
});

describe('computeTimeline', () => {
  it('spreads persistent events across their consecutive days', () => {
    const t = computeTimeline([mk('p', 1000, 'persistent', 80, 'persistent', 3)], NOW);
    const total = t.reduce((a, d) => a + d.total, 0);
    expect(total).toBe(3);
  });
  it('buckets transient events once', () => {
    const t = computeTimeline([mk('x', 1000, 'wildfire')], NOW);
    expect(t.reduce((a, d) => a + d.total, 0)).toBe(1);
  });
});

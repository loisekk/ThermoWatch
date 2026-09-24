/**
 * Instrument data adapters — pure, node-run (mirrors the server explanation
 * payload built in server/api/app/services/assessment.py).
 */
import { describe, expect, it } from 'vitest';
import {
  frpEnvelope,
  fusionFromExplanation,
  hourHistogram,
  intensityZ,
  isNightHour,
  isNewZone,
  prefersReducedMotion,
} from '../viz/vizData';

describe('fusionFromExplanation', () => {
  it('extracts sources + verdict from the server explanation payload', () => {
    const view = fusionFromExplanation({
      evidence_fusion: {
        fused_score: 0.62,
        fused_confidence: 0.75,
        dominant_source: 'thermal_residual',
        sources: [
          { name: 'thermal_residual', score: 0.8, weight: 1, confidence: 0.9 },
          { name: 'weather_context', score: 0.3, weight: 0.5, confidence: 0.6 },
        ],
      },
    });
    expect(view.fusedScore).toBeCloseTo(0.62);
    expect(view.fusedConfidence).toBeCloseTo(0.75);
    expect(view.dominantSource).toBe('thermal_residual');
    expect(view.sources).toHaveLength(2);
    expect(view.sources[0]).toEqual({
      name: 'thermal_residual',
      score: 0.8,
      weight: 1,
      confidence: 0.9,
    });
  });

  it('clamps scores/confidence into [0,1] and keeps weights raw', () => {
    const view = fusionFromExplanation({
      evidence_fusion: {
        fused_score: 1.7,
        sources: [{ name: 'x', score: -2, weight: 3, confidence: 5 }],
      },
    });
    expect(view.fusedScore).toBe(1);
    expect(view.sources[0]?.score).toBe(0);
    expect(view.sources[0]?.confidence).toBe(1);
    expect(view.sources[0]?.weight).toBe(3);
  });

  it('degrades to an honest empty view for missing/malformed payloads', () => {
    const cases: (Record<string, unknown> | null | undefined)[] = [
      null,
      undefined,
      {},
      { evidence_fusion: 'nope' },
      { evidence_fusion: { sources: 'x' } },
    ];
    for (const input of cases) {
      const view = fusionFromExplanation(input);
      expect(view.sources).toEqual([]);
      expect(view.fusedScore).toBe(0);
      expect(view.dominantSource).toBeNull();
    }
  });

  it('drops source entries without a name', () => {
    const view = fusionFromExplanation({
      evidence_fusion: { sources: [{ score: 0.5 }, { name: 'ok', score: 0.5 }] },
    });
    expect(view.sources.map((s) => s.name)).toEqual(['ok']);
  });
});

describe('intensityZ / isNewZone', () => {
  it('returns the z-score when finite', () => {
    expect(intensityZ({ intensity_z: 4.2 })).toBe(4.2);
    expect(intensityZ({ intensity_z: -1.5 })).toBe(-1.5);
  });

  it('returns null without a usable baseline value', () => {
    expect(intensityZ(null)).toBeNull();
    expect(intensityZ(undefined)).toBeNull();
    expect(intensityZ({})).toBeNull();
    expect(intensityZ({ intensity_z: null })).toBeNull();
    expect(intensityZ({ intensity_z: Number.NaN })).toBeNull();
    expect(intensityZ({ intensity_z: 'hot' as unknown as number })).toBeNull();
  });

  it('reads is_new_zone only as a real boolean true', () => {
    expect(isNewZone({ is_new_zone: true })).toBe(true);
    expect(isNewZone({ is_new_zone: false })).toBe(false);
    expect(isNewZone({ is_new_zone: 1 })).toBe(false);
    expect(isNewZone(null)).toBe(false);
  });
});

describe('frpEnvelope', () => {
  it('uses the facility band when provided (log1p space)', () => {
    const env = frpEnvelope([1, 2, 3], 10, 100);
    expect(env.baselineKnown).toBe(true);
    expect(env.lo).toBeCloseTo(Math.log1p(10));
    expect(env.hi).toBeCloseTo(Math.log1p(100));
    expect(env.lo).toBeLessThan(env.hi);
    // a band needs BOTH percentiles — half a band falls back honestly
    expect(frpEnvelope([1, 2, 3], 10, null).baselineKnown).toBe(false);
  });

  it('normalizes an inverted band instead of drawing a negative region', () => {
    const env = frpEnvelope([1], 100, 10);
    expect(env.baselineKnown).toBe(true);
    expect(env.lo).toBeLessThan(env.hi);
  });

  it('falls back to the data IQR and says so when no baseline exists', () => {
    const logs = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
    const env = frpEnvelope(logs);
    expect(env.baselineKnown).toBe(false);
    expect(env.lo).toBe(3); // q25 → index floor(0.25 * 12)
    expect(env.hi).toBe(9); // q75 → index floor(0.75 * 12)
  });

  it('stays finite for a single observation or none', () => {
    expect(frpEnvelope([2])).toEqual({ lo: 2, hi: 2, baselineKnown: false });
    expect(frpEnvelope([])).toEqual({ lo: 0, hi: 0, baselineKnown: false });
  });
});

describe('hourHistogram / isNightHour', () => {
  it('bins hours mod 24 and ignores non-finite input', () => {
    const counts = hourHistogram([0, 0, 6, 23, 24, 25, Number.NaN]);
    expect(counts).toHaveLength(24);
    expect(counts[0]).toBe(3); // two 0s and 24 → all midnight
    expect(counts[1]).toBe(1); // 25 → 01:00
    expect(counts[6]).toBe(1);
    expect(counts[23]).toBe(1);
    expect(counts.reduce((a, b) => a + b, 0)).toBe(6); // NaN dropped
  });

  it('marks 18:00–05:59 as night (dial wedge + bar colors)', () => {
    expect(isNightHour(18)).toBe(true);
    expect(isNightHour(23)).toBe(true);
    expect(isNightHour(0)).toBe(true);
    expect(isNightHour(5)).toBe(true);
    expect(isNightHour(6)).toBe(false);
    expect(isNightHour(12)).toBe(false);
    expect(isNightHour(17)).toBe(false);
  });
});

describe('prefersReducedMotion', () => {
  it('is false in the node test environment (no matchMedia)', () => {
    expect(prefersReducedMotion()).toBe(false);
  });
});

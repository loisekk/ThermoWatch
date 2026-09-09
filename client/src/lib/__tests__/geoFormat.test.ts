import { describe, expect, it } from 'vitest';
import { haversineKm } from '@/lib/geo/distance';
import { coordLabel, fmtInt, relTime } from '@/lib/utils/format';

describe('haversineKm', () => {
  it('Delhi–Jaipur ≈ 235 km', () => {
    const d = haversineKm(28.61, 77.21, 26.91, 75.79);
    expect(d).toBeGreaterThan(225);
    expect(d).toBeLessThan(245);
  });
  it('zero distance', () => expect(haversineKm(1, 1, 1, 1)).toBe(0));
});

describe('format', () => {
  it('fmtInt uses en-IN grouping', () => expect(fmtInt(1234)).toBe('1,234'));
  it('relTime buckets', () => {
    const now = 1_000_000;
    expect(relTime(now - 30_000, now)).toBe('30s ago');
    expect(relTime(now - 120_000, now)).toBe('2m ago');
    expect(relTime(now - 7_200_000, now)).toBe('2h ago');
  });
  it('coordLabel hemisphere suffixes', () => expect(coordLabel(-12.345, 96.0)).toBe('12.345°S 96.000°E'));
});

/**
 * Pure v2 client-layer tests — buildIncidentsQuery + V2ApiError only.
 * client.ts has no import-time side effects (window is touched only inside
 * request()), so a plain import is safe in the node test environment.
 */
import { describe, expect, it } from 'vitest';
import { V2ApiError, buildIncidentsQuery } from '../v2Client';
import type { QueueFilters } from '../v2Types';

const baseFilters = (over: Partial<QueueFilters> = {}): QueueFilters => ({
  status: 'all',
  activity: 'all',
  minConfidence: null,
  timeRangeHours: null,
  ...over,
});

const qs = (f: QueueFilters, cursor?: string | null, limit?: number) =>
  new URLSearchParams(buildIncidentsQuery(f, cursor, limit));

describe('buildIncidentsQuery', () => {
  it('emits only the limit for wide-open filters', () => {
    const p = qs(baseFilters());
    expect([...p.keys()]).toEqual(['limit']);
    expect(p.get('limit')).toBe('50');
  });

  it('serialises status/activity only when narrowed', () => {
    const narrowed = qs(baseFilters({ status: 'escalated', activity: 'acute' }));
    expect(narrowed.get('status')).toBe('escalated');
    expect(narrowed.get('activity')).toBe('acute');

    const open = qs(baseFilters());
    expect(open.get('status')).toBeNull();
    expect(open.get('activity')).toBeNull();
  });

  it('drops null/zero confidence and time-range filters', () => {
    const p = qs(baseFilters({ minConfidence: 0, timeRangeHours: 0 }));
    expect(p.get('min_confidence')).toBeNull();
    expect(p.get('start_time')).toBeNull();

    const nulls = qs(baseFilters());
    expect(nulls.get('min_confidence')).toBeNull();
    expect(nulls.get('start_time')).toBeNull();
  });

  it('encodes confidence and derives start_time from the hour window', () => {
    const before = Date.now();
    const p = qs(baseFilters({ minConfidence: 0.75, timeRangeHours: 24 }));
    expect(p.get('min_confidence')).toBe('0.75');

    const start = Date.parse(p.get('start_time') as string);
    const expected = before - 24 * 3_600_000;
    expect(Math.abs(start - expected)).toBeLessThan(5_000);
  });

  it('round-trips an encoded cursor and honours a custom limit', () => {
    const p = qs(baseFilters(), 'cur sor/+=x', 25);
    expect(p.get('cursor')).toBe('cur sor/+=x');
    expect(p.get('limit')).toBe('25');
  });

  it('omits an absent cursor', () => {
    expect(qs(baseFilters(), null).has('cursor')).toBe(false);
    expect(qs(baseFilters(), undefined).has('cursor')).toBe(false);
  });
});

describe('V2ApiError', () => {
  it('carries status and detail for panel rendering', () => {
    const err = new V2ApiError(409, { reason: 'version_conflict' }, 'API 409: /x');
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe('V2ApiError');
    expect(err.status).toBe(409);
    expect(err.detail).toEqual({ reason: 'version_conflict' });
    expect(err.message).toBe('API 409: /x');
  });
});

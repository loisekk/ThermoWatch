import { describe, expect, it } from 'vitest';
import { correlateNews } from '../newsCorrelate';
import type { NewsItem } from '../types';

const item = (lat: number, lon: number, at: string): NewsItem => ({
  id: 'x', provider: 'eonet', grade: 'event', title: 't', url: 'u',
  published_at: at, lat, lon, country: null, source_domain: null,
  categories: [], matched_terms: [], nearby_event_ids: [], correlation_km: null,
  correlation_dt_h: null,
});
const A = { lat: 22.8, lon: 86.2, atMs: Date.parse('2026-09-14T00:00:00Z') };

describe('newsCorrelate', () => {
  it('includes <=75 km and <=72 h, excludes beyond (inclusive bounds)', () => {
    const near = item(22.8 + 0.6, 86.2, '2026-09-13T00:00:00Z');   // ~66 km, 24 h
    const far = item(22.8 + 1.2, 86.2, '2026-09-13T00:00:00Z');    // ~133 km
    const old = item(22.8 + 0.1, 86.2, '2026-09-09T00:00:00Z');    // ~120 h
    const r = correlateNews([near, far, old], A);
    expect(r).toHaveLength(1);
    expect(r[0].distance_km).toBeLessThanOrEqual(75);
  });

  it('sorts by distance ascending', () => {
    const a = item(22.8 + 0.5, 86.2, '2026-09-13T12:00:00Z');
    const b = item(22.8 + 0.2, 86.2, '2026-09-13T20:00:00Z');
    const r = correlateNews([a, b], A);
    expect(r[0].id).toBe('x');
    expect(r).toHaveLength(2);
    expect(r[0].distance_km).toBeLessThan(r[1].distance_km);
  });

  it('skips items without coordinates (country-grade articles)', () => {
    const noCoords = { ...item(0, 0, '2026-09-13T00:00:00Z'), lat: null, lon: null };
    expect(correlateNews([noCoords], A)).toEqual([]);
  });

  it('keeps items when the anchor has no timestamp (dt unbounded)', () => {
    const near = item(22.8 + 0.3, 86.2, '2026-09-01T00:00:00Z');
    expect(correlateNews([near], { lat: A.lat, lon: A.lon, atMs: null })).toHaveLength(1);
  });
});

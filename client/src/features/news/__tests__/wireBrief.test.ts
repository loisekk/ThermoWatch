import { expect, it } from 'vitest';
import { buildWireBrief } from '../wireBrief';
import type { NewsItem } from '../types';

const now = new Date('2026-09-14T00:00:00Z');
const item = (over: Partial<NewsItem> = {}): NewsItem => ({
  id: '1', provider: 'eonet', grade: 'event', title: 'Wildfire X', url: 'u',
  published_at: '2026-09-13T22:00:00Z', lat: 1, lon: 1, country: null,
  source_domain: null, categories: ['wildfire'], matched_terms: [],
  nearby_event_ids: [], correlation_km: null, correlation_dt_h: null, ...over,
});

it('empty window is honest', () => {
  const b = buildWireBrief([], [], now);
  expect(b.headline).toBe('No wire items in window');
  expect(b.bullets).toEqual([]);
  expect(b.correlated).toBe(0);
  expect(b.newest_source_age_h).toBeNull();
});

it('counts categories and picks the correlated headline', () => {
  const i = item();
  const corr = { ...i, id: '2', distance_km: 10.4, dt_hours: 2 };
  const b = buildWireBrief([i, item({ id: '2', title: 'Refinery blaze', categories: ['industrial', 'wildfire'] })], [corr], now);
  expect(b.headline).toBe('Wildfire X');
  expect(b.counts.wildfire).toBe(2);
  expect(b.counts.industrial).toBe(1);
  expect(b.correlated).toBe(1);
  expect(b.newest_source_age_h).toBe(2);
});

it('bullets prefer correlated items and cap at 3', () => {
  const corr = { ...item({ id: 'c1', title: 'corr' }), distance_km: 5.0, dt_hours: 1.0 };
  const b = buildWireBrief(
    [item({ id: 'i1', title: 'one' }), item({ id: 'i2', title: 'two' }), item({ id: 'i3', title: 'three' })],
    [corr], now);
  expect(b.bullets[0]).toContain('[eonet] corr');
  expect(b.bullets).toHaveLength(3);
});

/**
 * Pure queue-helper tests (vitest node env — no React, no fetch, no DOM).
 */
import { describe, expect, it } from 'vitest';
import {
  flattenQueuePages,
  freshnessLabel,
  routeStreamEvent,
  shouldProcessSequence,
} from '../queueUtils';
import type { IncidentListResponse, IncidentSummary } from '@/services/api/v2Types';

function inc(id: string): IncidentSummary {
  return {
    id,
    status: 'needs_review',
    version: 1,
    centroid_latitude: 12.34,
    centroid_longitude: 56.78,
    first_seen_at: '2026-01-01T00:00:00Z',
    last_seen_at: '2026-01-02T00:00:00Z',
    observation_count: 3,
    current_assessment: null,
    days_active: 1,
  };
}

function page(ids: string[]): IncidentListResponse {
  return { incidents: ids.map(inc), next_cursor: null, total_approx: ids.length };
}

describe('flattenQueuePages', () => {
  it('returns an empty list for missing pages', () => {
    expect(flattenQueuePages(undefined)).toEqual([]);
  });

  it('returns [] for an empty page list', () => {
    expect(flattenQueuePages([])).toEqual([]);
  });

  it('flattens pages preserving order', () => {
    const rows = flattenQueuePages([page(['a', 'b']), page(['c'])]);
    expect(rows.map((r) => r.id)).toEqual(['a', 'b', 'c']);
  });

  it('deduplicates incidents repeated across pages, keeping the first copy', () => {
    const rows = flattenQueuePages([page(['a', 'b']), page(['b', 'c']), page(['a'])]);
    expect(rows.map((r) => r.id)).toEqual(['a', 'b', 'c']);
  });
});

describe('routeStreamEvent', () => {
  const routes = (event_type: string, entity_type = 'incident', entity_id = 'inc-1') =>
    routeStreamEvent({ event_type, entity_type, entity_id }).map((r) => r.queryKey);

  it('invalidates list + detail for incident lifecycle events', () => {
    for (const event_type of ['incident.created', 'incident.updated', 'incident.reviewed']) {
      expect(routes(event_type)).toEqual([['incidents'], ['incident', 'inc-1']]);
    }
  });

  it('falls back to list-only when the entity is not an incident', () => {
    expect(routes('incident.updated', 'observation')).toEqual([['incidents']]);
  });

  it('routes assessment events detail-first, then list', () => {
    expect(routes('assessment.created')).toEqual([['incident', 'inc-1'], ['incidents']]);
  });

  it('ignores unknown event types (forward-compatible)', () => {
    expect(routes('sensor.heartbeat')).toEqual([]);
    expect(routes('context.retrieved')).toEqual([]);
  });
});

describe('shouldProcessSequence', () => {
  it('accepts strictly increasing sequences', () => {
    expect(shouldProcessSequence(1, 0)).toBe(true);
    expect(shouldProcessSequence(42, 7)).toBe(true);
  });

  it('rejects replays and out-of-order frames', () => {
    expect(shouldProcessSequence(7, 7)).toBe(false);
    expect(shouldProcessSequence(6, 7)).toBe(false);
    expect(shouldProcessSequence(0, 0)).toBe(false);
  });
});

describe('freshnessLabel', () => {
  const now = Date.parse('2026-06-01T12:00:00Z');
  const ago = (ms: number) => new Date(now - ms).toISOString();

  it('collapses sub-hour stamps', () => {
    expect(freshnessLabel(ago(20 * 60_000), now)).toBe('<1h ago');
  });

  it('labels whole hours below a day', () => {
    expect(freshnessLabel(ago(5 * 3_600_000), now)).toBe('5h ago');
    expect(freshnessLabel(ago(23 * 3_600_000), now)).toBe('23h ago');
  });

  it('switches to whole days at 24h', () => {
    expect(freshnessLabel(ago(24 * 3_600_000), now)).toBe('1d ago');
    expect(freshnessLabel(ago(48 * 3_600_000), now)).toBe('2d ago');
  });
});

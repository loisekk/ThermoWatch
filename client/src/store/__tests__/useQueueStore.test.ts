/**
 * Queue UI store — selection, filters, drawer flag. Server state lives in
 * TanStack Query; this file only pins the store's own transitions.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { useQueueStore } from '../useQueueStore';

const st = () => useQueueStore.getState();

beforeEach(() => {
  st().resetFilters();
  st().selectIncident(null);
  st().setDrawerOpen(false);
});

describe('initial state', () => {
  it('starts on the needs_review queue with nothing selected', () => {
    expect(st().filters).toEqual({
      status: 'needs_review',
      activity: 'all',
      minConfidence: null,
      timeRangeHours: null,
    });
    expect(st().selectedIncidentId).toBeNull();
    expect(st().drawerOpen).toBe(false);
  });
});

describe('setFilters', () => {
  it('merges partial updates without touching siblings', () => {
    st().setFilters({ minConfidence: 0.8 });
    expect(st().filters).toEqual({
      status: 'needs_review',
      activity: 'all',
      minConfidence: 0.8,
      timeRangeHours: null,
    });

    st().setFilters({ status: 'all', timeRangeHours: 24 });
    expect(st().filters).toEqual({
      status: 'all',
      activity: 'all',
      minConfidence: 0.8,
      timeRangeHours: 24,
    });
  });
});

describe('resetFilters', () => {
  it('restores defaults after narrowing', () => {
    st().setFilters({
      status: 'dismissed',
      activity: 'persistent',
      minConfidence: 0.5,
      timeRangeHours: 6,
    });
    st().resetFilters();
    expect(st().filters).toEqual({
      status: 'needs_review',
      activity: 'all',
      minConfidence: null,
      timeRangeHours: null,
    });
  });
});

describe('selection & drawer', () => {
  it('selecting an incident opens the drawer', () => {
    st().selectIncident('inc-42');
    expect(st().selectedIncidentId).toBe('inc-42');
    expect(st().drawerOpen).toBe(true);
  });

  it('clearing the selection closes the drawer', () => {
    st().selectIncident('inc-42');
    st().selectIncident(null);
    expect(st().selectedIncidentId).toBeNull();
    expect(st().drawerOpen).toBe(false);
  });

  it('drawer can be closed without dropping the selection', () => {
    st().selectIncident('inc-42');
    st().setDrawerOpen(false);
    expect(st().selectedIncidentId).toBe('inc-42');
    expect(st().drawerOpen).toBe(false);
  });
});

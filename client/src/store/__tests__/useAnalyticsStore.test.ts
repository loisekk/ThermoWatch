import { beforeEach, describe, expect, it } from 'vitest';
import { WINDOW_BOUNDS, useAnalyticsStore } from '@/store/useAnalyticsStore';

const H = 3_600_000;

function reset(): void {
  useAnalyticsStore.getState().resetTimeRange();
  useAnalyticsStore.getState().pause();
  useAnalyticsStore.getState().setAdvancedMode(false);
  useAnalyticsStore.getState().setDuckDBReady(false);
  useAnalyticsStore.getState().setLayers({ hexagonDensity: true, buildingExtrusion: true, spreadRings: true, timeSlider: true });
}

describe('useAnalyticsStore', () => {
  beforeEach(reset);

  it('initialises the scrubber to the full 14-day window', () => {
    const { timeRange } = useAnalyticsStore.getState();
    expect(timeRange.start).toBe(WINDOW_BOUNDS.min);
    expect(timeRange.end).toBe(WINDOW_BOUNDS.max);
    expect(WINDOW_BOUNDS.max - WINDOW_BOUNDS.min).toBe(14 * 86_400_000);
  });

  it('tick() slides the window forward by 1 h × speed while playing', () => {
    const s = useAnalyticsStore.getState();
    s.play();
    s.setTimeRange({ start: WINDOW_BOUNDS.min, end: WINDOW_BOUNDS.min + 2 * H });
    s.tick();
    let t = useAnalyticsStore.getState().timeRange;
    expect(t.end).toBe(WINDOW_BOUNDS.min + 3 * H);
    expect(t.start).toBe(WINDOW_BOUNDS.min);

    s.setTimeRange({ speed: 2 });
    s.tick();
    t = useAnalyticsStore.getState().timeRange;
    expect(t.end).toBe(WINDOW_BOUNDS.min + 5 * H); // +2 h at 2x
  });

  it('tick() wraps back to the window start when reaching "now"', () => {
    const s = useAnalyticsStore.getState();
    s.play();
    const dur = 2 * H;
    s.setTimeRange({ start: WINDOW_BOUNDS.max - dur, end: WINDOW_BOUNDS.max });
    s.tick(); // end would exceed max → wrap
    const t = useAnalyticsStore.getState().timeRange;
    expect(t.start).toBe(WINDOW_BOUNDS.min);
    expect(t.end).toBe(WINDOW_BOUNDS.min + dur);
  });

  it('tick() is a no-op while paused', () => {
    const s = useAnalyticsStore.getState();
    s.setTimeRange({ start: WINDOW_BOUNDS.min, end: WINDOW_BOUNDS.min + 2 * H });
    s.tick();
    expect(useAnalyticsStore.getState().timeRange.end).toBe(WINDOW_BOUNDS.min + 2 * H);
  });

  it('setLayers merges partial visibility and advancedMode toggles', () => {
    const s = useAnalyticsStore.getState();
    s.setLayers({ hexagonDensity: false });
    expect(useAnalyticsStore.getState().layers.hexagonDensity).toBe(false);
    expect(useAnalyticsStore.getState().layers.buildingExtrusion).toBe(true);
    expect(useAnalyticsStore.getState().layers.timeSlider).toBe(true);
    const s2 = useAnalyticsStore.getState();
    s2.setAdvancedMode(true);
    expect(useAnalyticsStore.getState().advancedMode).toBe(true);
  });
});

import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { PANEL_CLAMP, panelWidth, useUIStore } from '../useUIStore';

const store = new Map<string, string>();
const ls = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, v),
  clear: () => store.clear(),
};

beforeEach(() => {
  store.clear();
  vi.stubGlobal('localStorage', ls);
});
afterEach(() => vi.unstubAllGlobals());

it('clamps, persists and resets panel sizes', () => {
  const st = () => useUIStore.getState();
  st().setPanelSize('rightDock', 9999);
  expect(st().panelSizes.rightDock).toBe(PANEL_CLAMP.rightDock[1]);
  st().setPanelSize('rightDock', 500);
  expect(JSON.parse(localStorage.getItem('tw.panelSizes.v1') as string).rightDock).toBe(500);
  st().resetPanelSize('rightDock');
  expect(st().panelSizes.rightDock).toBe(PANEL_CLAMP.rightDock[2]);
});

it('panelWidth falls back to the default and clamps persisted values', () => {
  expect(panelWidth({}, 'eventDrawer')).toBe(400);
  expect(panelWidth({ eventDrawer: 99999 }, 'eventDrawer')).toBe(720);
  expect(panelWidth({ eventDrawer: 10 }, 'eventDrawer')).toBe(360);
});

it("panel key 'news' toggles through the same setPanel surface", () => {
  const st = () => useUIStore.getState();
  st().setPanel('news');
  expect(st().panel).toBe('news');
  st().setPanel('overview');
  expect(st().panel).toBe('overview');
});

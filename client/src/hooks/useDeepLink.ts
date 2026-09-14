import { useEffect } from 'react';
import { useUIStore, type PanelKey } from '@/store/useUIStore';

const PANEL_MAP: Record<string, PanelKey> = {
  o: 'overview', p: 'persistence', a: 'alerts', f: 'facilities', g: 'agent',
  m: 'predict', k: 'model', x: 'analytics', h: 'history', n: 'news',
};

/** Reads /app.html?vp=&panel=&lat=&lon= once on mount and applies it to the stores. */
export function useDeepLink(): void {
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const ui = useUIStore.getState();
    const vp = q.get('vp');
    if (vp === '2d' || vp === '3d') ui.setViewMode(vp);
    const panel = q.get('panel');
    if (panel && panel in PANEL_MAP) ui.setPanel(PANEL_MAP[panel]);
    const lat = parseFloat(q.get('lat') ?? '');
    const lon = parseFloat(q.get('lon') ?? '');
    if (Number.isFinite(lat) && Number.isFinite(lon)) ui.requestFocus(lat, lon);
  }, []);
}

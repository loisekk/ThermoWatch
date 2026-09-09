import { useEffect, useMemo, useRef } from 'react';
import type { FeatureCollection, Geometry, Position } from 'geojson';
import world from '@/assets/world-110m.json';
import { BORDER, LAND, OCEAN } from '@/config/worldStyle';
import { COUNTRY_LABELS, countryCounts } from '@/lib/geo/countryIndex';
import { CLASS_META } from '@/config/constants';
import { useFireStore } from '@/store/useFireStore';
import { useAnalyticsStore } from '@/store/useAnalyticsStore';
import { useMapDiagStore } from '@/store/useMapDiagStore';
import { filterEvents } from '@/selectors/fireSelectors';
import type { FireEvent } from '@/types/domain';

const W = 2000;
const H = 1000;
const px = (lon: number) => ((lon + 180) / 360) * W;
const py = (lat: number) => ((90 - lat) / 180) * H;

const PATHS: Path2D[] = ((world as unknown as FeatureCollection<Geometry, Record<string, unknown>>).features).map((f) => {
  const path = new Path2D();
  const walk = (node: unknown): void => {
    if (Array.isArray(node) && typeof node[0] === 'number') {
      const ring = node as Position[];
      ring.forEach(([lon, lat], i) => (i === 0 ? path.moveTo(px(lon), py(lat)) : path.lineTo(px(lon), py(lat))));
      path.closePath();
    } else if (Array.isArray(node)) node.forEach(walk);
  };
  walk((f.geometry as unknown as { coordinates: unknown }).coordinates);
  return path;
});

export function FallbackWorldMap({ events }: { events: FireEvent[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawRef = useRef<() => void>(() => {});
  const view = useRef({ scale: 1, ox: 0, oy: 0, drag: null as null | { x: number; y: number } });
  const filters = useFireStore((s) => s.filters);
  const facilities = useFireStore((s) => s.facilities);
  const select = useFireStore((s) => s.select);
  const layers = useAnalyticsStore((s) => s.layers);
  const timeRange = useAnalyticsStore((s) => s.timeRange);
  const setMapApi = useMapDiagStore((s) => s.setMapApi);

  const filtered = useMemo(
    () => filterEvents(events, filters).filter((e) => e.detectedAt >= timeRange.start && e.detectedAt <= timeRange.end),
    [events, filters, timeRange],
  );
  const counts = useMemo(() => countryCounts(filtered), [filtered]);

  // Renderer-agnostic control API (same contract as the MapLibre path).
  useEffect(() => {
    setMapApi({
      zoomIn: () => { view.current.scale = Math.min(8, view.current.scale * 1.4); drawRef.current(); },
      zoomOut: () => { view.current.scale = Math.max(0.6, view.current.scale / 1.4); drawRef.current(); },
      reset: () => { view.current = { ...view.current, scale: 1, ox: 0, oy: 0 }; drawRef.current(); },
    });
    return () => setMapApi(null);
  }, [setMapApi]);
useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const draw = () => {
      const { scale, ox, oy } = view.current;
      const cw = canvas.clientWidth, ch = canvas.clientHeight;
      canvas.width = cw * devicePixelRatio; canvas.height = ch * devicePixelRatio;
      ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
      ctx.fillStyle = OCEAN; ctx.fillRect(0, 0, cw, ch);

      const base = Math.min(cw / W, ch / H) * scale;
      const tx = (cw - W * base) / 2 + ox, ty = (ch - H * base) / 2 + oy;
      ctx.setTransform(devicePixelRatio * base, 0, 0, devicePixelRatio * base, devicePixelRatio * tx, devicePixelRatio * ty);

      PATHS.forEach((p, i) => {
        const n = counts.get(i) ?? 0;
        ctx.fillStyle = !layers.choropleth ? LAND : n >= 30 ? '#46301f' : n >= 10 ? '#33302a' : n > 0 ? '#232a31' : LAND;
        ctx.fill(p);
        ctx.strokeStyle = BORDER; ctx.lineWidth = 0.7 / base; ctx.stroke(p);
      });

      if (layers.labels) {
        ctx.fillStyle = '#6b7684';
        ctx.font = `${11 / base}px monospace`;
        ctx.textAlign = 'center';
        for (const l of COUNTRY_LABELS) ctx.fillText(l.name.toUpperCase(), px(l.centroid[0]), py(l.centroid[1]));
      }

      if (layers.facilities) {
        ctx.fillStyle = '#10161d'; ctx.strokeStyle = '#7d8da1'; ctx.lineWidth = 1 / base;
        for (const f of facilities) { ctx.beginPath(); ctx.arc(px(f.lon), py(f.lat), 2.5 / base, 0, 7); ctx.fill(); ctx.stroke(); }
      }
      if (layers.persistentRings) {
        ctx.strokeStyle = CLASS_META.persistent.color; ctx.lineWidth = 1.2 / base;
        for (const e of filtered) if (e.persistence.regime === 'persistent') { ctx.beginPath(); ctx.arc(px(e.lon), py(e.lat), 9 / base, 0, 7); ctx.stroke(); }
      }
      for (const e of filtered) {
        ctx.fillStyle = CLASS_META[e.classification.primary].color;
        ctx.beginPath();
        ctx.arc(px(e.lon), py(e.lat), (3 + Math.min(e.frp, 900) / 160) / base, 0, 7);
        ctx.fill();
      }
    };
    drawRef.current = draw;
    draw();

    const ro = new ResizeObserver(draw);
    ro.observe(canvas);

    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault();
      view.current.scale = Math.min(8, Math.max(0.6, view.current.scale * (ev.deltaY < 0 ? 1.15 : 0.87)));
      draw();
    };
    const onDown = (ev: MouseEvent) => { view.current.drag = { x: ev.clientX, y: ev.clientY }; };
    const onMove = (ev: MouseEvent) => {
      if (!view.current.drag) return;
      view.current.ox += ev.clientX - view.current.drag.x;
      view.current.oy += ev.clientY - view.current.drag.y;
      view.current.drag = { x: ev.clientX, y: ev.clientY };
      draw();
    };
    const onUp = (ev: MouseEvent) => {
      const wasDrag = view.current.drag && (Math.abs(ev.clientX - view.current.drag.x) > 3 || Math.abs(ev.clientY - view.current.drag.y) > 3);
      view.current.drag = null;
      if (wasDrag) return;
      const rect = canvas.getBoundingClientRect();
      const { scale, ox, oy } = view.current;
      const base = Math.min(rect.width / W, rect.height / H) * scale;
      const tx = (rect.width - W * base) / 2 + ox, ty = (rect.height - H * base) / 2 + oy;
      const wx = (ev.clientX - rect.left - tx) / base, wy = (ev.clientY - rect.top - ty) / base;
      let best: FireEvent | null = null; let bestD = 12 / base;
      for (const e of filtered) {
        const d = Math.hypot(px(e.lon) - wx, py(e.lat) - wy);
        if (d < bestD) { bestD = d; best = e; }
      }
      if (best) select(best.id);
    };
    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('mousedown', onDown);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      ro.disconnect();
      canvas.removeEventListener('wheel', onWheel);
      canvas.removeEventListener('mousedown', onDown);
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [filtered, counts, layers, facilities, select]);

  return <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" aria-label="2D world fire map (canvas renderer)" />;
}
